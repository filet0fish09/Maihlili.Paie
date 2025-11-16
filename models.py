from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta
import calendar
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# ----------------------------------------------------------------------
# 🏰 1. MODÈLE : Establishment (Établissement)
# ----------------------------------------------------------------------
class Establishment(db.Model):
    __tablename__ = 'establishment'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    
    # Relations (backrefs définis dans User et Employee)
    
    def __repr__(self):
        return f'<Establishment {self.name}>'

# ----------------------------------------------------------------------
# 👤 2. MODÈLE : User (Utilisateur)
# ----------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    
    # Rôles
    is_manager = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_super_admin = db.Column(db.Boolean, default=False) # NOUVEAU : Ultra-Admin
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Association à l'établissement
    # Utilisé SET NULL pour les Ultra-Admins qui ne devraient pas être supprimés avec l'établissement
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishment.id', ondelete='SET NULL'), nullable=True)
    establishment = db.relationship('Establishment', backref='users')
    
    # Relations
    employee = db.relationship('Employee', backref='user', uselist=False)
    
    # Méthodes
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'

# ----------------------------------------------------------------------
# 👥 Association Many-to-Many entre Employee et Team
# ----------------------------------------------------------------------
employee_teams = db.Table('employee_teams',
    db.Column('employee_id', db.Integer, db.ForeignKey('employees.id'), primary_key=True),
    db.Column('team_id', db.Integer, db.ForeignKey('teams.id'), primary_key=True)
)

# ----------------------------------------------------------------------
# 💼 3. MODÈLE : Employee (Employé)
# ----------------------------------------------------------------------
class Employee(db.Model):
    __tablename__ = 'employees'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=True)
    
    # Champs dupliqués dans votre code, on utilise la version complète 'full_name'
    full_name = db.Column(db.String(100), nullable=False) 
    position = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Contrat et Salaires
    contract_hours_per_week = db.Column(db.Float, default=35.0)
    contract_hours_per_month = db.Column(db.Float, default=151.67)
    contract_type = db.Column(db.String(20), default="CDI")
    base_hourly_rate = db.Column(db.Float, default=10.0) # Ajouté depuis la première définition
    
    # Association à l'établissement (NON NULL car doit appartenir à un établissement)
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishment.id'), nullable=False)
    establishment = db.relationship('Establishment', backref='employees')

    # Association à une seule équipe (pour les managers) - Ajouté pour la cohérence
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True)
    
    # Relations
    assignments = db.relationship('Assignment', backref='employee', lazy='dynamic', cascade='all, delete-orphan')
    # Relation Many-to-Many via table intermédiaire
    teams = db.relationship(
        'Team', 
        secondary=employee_teams, 
        backref=db.backref('members', lazy='dynamic')
    )
    # Relation pour les équipes managées
    managed_teams = db.relationship('Team', foreign_keys='Team.manager_id', backref='manager', lazy=True)

    # --- Méthodes de suivi des heures (conservées) ---

    def get_worked_hours_for_month(self, year=None, month=None):
        if not year: year = datetime.now().year
        if not month: month = datetime.now().month
        
        start_date = datetime(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        end_date = datetime(year, month, last_day, 23, 59, 59)
        
        monthly_assignments = Assignment.query.filter(
            Assignment.employee_id == self.id,
            Assignment.start >= start_date,
            Assignment.start <= end_date,
        ).all()
        
        total_hours = 0
        for assignment in monthly_assignments:
            duration = assignment.end - assignment.start
            total_hours += duration.total_seconds() / 3600
            
        return round(total_hours, 2)

    def get_hours_difference_for_month(self, year=None, month=None):
        worked_hours = self.get_worked_hours_for_month(year, month)
        contract_hours = self.contract_hours_per_month or 151.67
        difference = worked_hours - contract_hours
        
        return {
            'worked_hours': worked_hours,
            'contract_hours': contract_hours,
            'difference': round(difference, 2),
            'percentage': round((worked_hours / contract_hours * 100), 1) if contract_hours > 0 else 0,
            'status': 'over' if difference > 0 else 'under' if difference < 0 else 'exact'
        }

    # ... (autres méthodes omises pour la concision, mais elles sont conservées) ...

    @property
    def current_month_hours_summary(self):
        return self.get_hours_difference_for_month()

    def update_contract_hours(self, hours_per_week):
        self.contract_hours_per_week = hours_per_week
        self.contract_hours_per_month = round(hours_per_week * 52 / 12, 2)

    def __repr__(self):
        return f'<Employee {self.full_name} - {self.establishment.name if self.establishment else "None"}>'

# ----------------------------------------------------------------------
# 📅 4. MODÈLE : Shift (Type de Quart)
# ----------------------------------------------------------------------
class Shift(db.Model):
    __tablename__ = 'shifts'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    color = db.Column(db.String(7), default='#3B82F6') 
    
    # Nouveaux champs
    created_by = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    employees_needed = db.Column(db.Integer, default=3)
    
    # Relations
    assignments = db.relationship('Assignment', backref='shift', lazy=True)
    
    def __repr__(self):
        return f'<Shift {self.name} {self.start_time}-{self.end_time}>'

# ----------------------------------------------------------------------
# 🔗 5. MODÈLE : Team (Équipe)
# ----------------------------------------------------------------------
class Team(db.Model):
    __tablename__ = 'teams'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    
    # Le manager est un Employee
    manager_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True) 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations (membres déjà définis dans Employee.teams)
    
    def __repr__(self):
        return f'<Team {self.name}>'

# ----------------------------------------------------------------------
# 🗓️ 6. MODÈLE : Assignment (Assignation)
# ----------------------------------------------------------------------
class Assignment(db.Model):
    __tablename__ = 'assignments'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False)
    shift_id = db.Column(db.Integer, db.ForeignKey('shifts.id', ondelete='SET NULL'), nullable=True) # SET NULL pour le shift
    
    start = db.Column(db.DateTime, nullable=False)
    end = db.Column(db.DateTime, nullable=False)
    
    # Nouveaux champs
    status = db.Column(db.String(20), default='scheduled')
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # ID de l'utilisateur créateur
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    timesheet_entries = db.relationship('TimeSheetEntry', backref='assignment', lazy=True, cascade='all, delete-orphan')
    creator = db.relationship('User', backref='created_assignments', lazy=True, foreign_keys=[created_by])
    
    @property
    def duration_hours(self):
        duration = self.end - self.start
        return round(duration.total_seconds() / 3600, 2)
    
    def __repr__(self):
        return f'<Assignment {self.employee_id} - {self.shift_id} on {self.start}>'

# ----------------------------------------------------------------------
# ⏱️ 7. MODÈLE : TimeSheetEntry (Feuille de Temps)
# ----------------------------------------------------------------------
class TimeSheetEntry(db.Model):
    __tablename__ = 'timesheet_entries'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # CASCADE est crucial pour le nettoyage
    assignment_id = db.Column(
        db.Integer, 
        db.ForeignKey('assignments.id', ondelete='CASCADE'), 
        nullable=False
    )
    
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    
    clock_in = db.Column(db.DateTime, nullable=False)
    clock_out = db.Column(db.DateTime)
    entry_type = db.Column(db.String(50), default='work') 
    
    # Relations
    employee = db.relationship('Employee', backref='timesheet_records', lazy=True, foreign_keys=[employee_id])
    
    @property
    def actual_duration_hours(self):
        if self.clock_out:
            duration = self.clock_out - self.clock_in
            return round(duration.total_seconds() / 3600, 2)
        return 0
        
    def __repr__(self):
        return f'<TimeSheetEntry {self.id} for Assignment {self.assignment_id}>'
