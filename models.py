from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta
import calendar
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_manager = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    # ⭐ AJOUT : Champ is_super_admin
    is_super_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    employee = db.relationship('Employee', backref='user', uselist=False)
    
    # Méthodes
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'

class Employee(db.Model):
    __tablename__ = 'employees'
    
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    position = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'))
    
    # ⭐ NOUVEAU : Clé étrangère vers Establishment
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=True)
    
    # NOUVEAUX CHAMPS pour les heures contractuelles
    contract_hours_per_week = db.Column(db.Float, default=35.0)
    contract_hours_per_month = db.Column(db.Float, default=151.67)
    contract_type = db.Column(db.String(20), default="CDI")
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    assignments = db.relationship('Assignment', backref='employee', lazy=True, cascade='all, delete-orphan')
    managed_teams = db.relationship('Team', foreign_keys='Team.manager_id', backref='manager', lazy=True)
    
    # ⭐ MODIFICATION CRUCIALE: Utilisation de back_populates pour éviter le conflit
    establishment = db.relationship('Establishment', back_populates='employees', lazy=True)
    
    @property
    def current_establishment(self):
        """Retourne l'établissement de l'employé, soit par lien direct, soit par son équipe."""
        if self.establishment:
            return self.establishment
        if self.team and self.team.establishment: # Vérifie le lien de l'équipe
            return self.team.establishment
        return None
        
    def can_be_managed_by(self, user):
        """Vérifie si cet employé peut être géré par l'utilisateur (manager/admin) donné."""
        if not user or not user.is_manager:
            return False
        
        # L'admin/super-admin peut tout gérer
        if user.is_admin or user.is_super_admin:
            return True
        
        manager_employee = user.employee
        if not manager_employee:
            return False

        # Si l'employé est dans une équipe, vérifier si le manager est le responsable de cette équipe
        if self.team_id:
            if self.team and self.team.manager_id == manager_employee.id:
                return True
        
        managed_teams_count = Team.query.filter_by(manager_id=manager_employee.id).count()
        if not self.team_id and managed_teams_count > 0:
             return True

        return False

    def get_worked_hours_for_month(self, year=None, month=None):
        """Calcule les heures travaillées pour un mois donné"""
        if not year:
            year = datetime.now().year
        if not month:
            month = datetime.now().month
            
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
        """Calcule la différence entre heures travaillées et contractuelles"""
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

    def get_monthly_hours_history(self, months_count=6):
        """Retourne l'historique des heures sur les derniers mois"""
        history = []
        current_date = datetime.now()
        
        for i in range(months_count):
            year = current_date.year
            month = current_date.month - i
            
            while month <= 0:
                month += 12
                year -= 1
            
            target_date = datetime(year, month, 1)
            
            month_data = self.get_hours_difference_for_month(year, month)
            month_data['month'] = target_date.strftime('%B %Y')
            month_data['month_short'] = target_date.strftime('%m/%Y')
            
            history.append(month_data)
            
        return list(reversed(history))

    @property
    def current_month_hours_summary(self):
        """Résumé rapide du mois en cours"""
        return self.get_hours_difference_for_month()

    def update_contract_hours(self, hours_per_week):
        """Met à jour les heures contractuelles"""
        self.contract_hours_per_week = hours_per_week
        self.contract_hours_per_month = round(hours_per_week * 52 / 12, 2)

    def __repr__(self):
        # ⭐ CORRECTION DU SYNTAX ERROR: ajout du '>' de fin
        return f'<Employee {self.full_name} - {self.contract_hours_per_week}h/sem>'


class Team(db.Model):
    __tablename__ = 'teams'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    manager_id = db.Column(db.Integer, db.ForeignKey('employees.id'))
    
    # ⭐ NOUVEAU : Lien vers l'établissement pour l'équipe
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=True) 
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    members = db.relationship('Employee', foreign_keys='Employee.team_id', backref='team', lazy=True)
    
    # ⭐ NOUVEAU : Relation vers Establishment (avec back_populates)
    establishment = db.relationship('Establishment', back_populates='teams', lazy=True)

    def __repr__(self):
        return f'<Team {self.name}>'


class Shift(db.Model):
    __tablename__ = 'shifts'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    color = db.Column(db.String(7), default='#3B82F6')
    created_by = db.Column(db.Integer, db.ForeignKey('employees.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    employees_needed = db.Column(db.Integer, default=3)
    
    # Relations
    assignments = db.relationship('Assignment', backref='shift', lazy=True)
    
    @property
    def duration_hours(self):
        """Calcule la durée du shift en heures"""
        start = datetime.combine(datetime.today(), self.start_time)
        end = datetime.combine(datetime.today(), self.end_time)
        
        if end < start:
            end += timedelta(days=1)
        
        duration = end - start
        return duration.total_seconds() / 3600
    
    def __repr__(self):
        return f'<Shift {self.name} {self.start_time}-{self.end_time}>'


class Assignment(db.Model):
    __tablename__ = 'assignments'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    shift_id = db.Column(db.Integer, db.ForeignKey('shifts.id'), nullable=False)
    start = db.Column(db.DateTime, nullable=False)
    end = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='scheduled')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Relations
    timesheet_entries = db.relationship('TimeSheetEntry', backref='assignment', lazy=True, cascade='all, delete-orphan')
    creator = db.relationship('User', backref='created_assignments', lazy=True, foreign_keys=[created_by])

    @property
    def duration_hours(self):
        """Calcule la durée de l'assignation en heures"""
        duration = self.end - self.start
        return round(duration.total_seconds() / 3600, 2)
    
    def __repr__(self):
        return f'<Assignment {self.employee_id} - {self.shift_id} on {self.start}>'

class TimeSheetEntry(db.Model):
    __tablename__ = 'timesheet_entries'
    
    id = db.Column(db.Integer, primary_key=True)
    
    assignment_id = db.Column(
        db.Integer, 
        db.ForeignKey('assignments.id', ondelete='CASCADE'), 
        nullable=False
    )
    
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    
    clock_in = db.Column(db.DateTime, nullable=False)
    clock_out = db.Column(db.DateTime)
    
    entry_type = db.Column(db.String(50), default='work') 
    
    employee = db.relationship('Employee', backref='timesheet_records', lazy=True, foreign_keys=[employee_id])
    
    @property
    def actual_duration_hours(self):
        if self.clock_out:
            duration = self.clock_out - self.clock_in
            return round(duration.total_seconds() / 3600, 2)
        return 0
        
    def __repr__(self):
        return f'<TimeSheetEntry {self.id} for Assignment {self.assignment_id}>'

# ⭐ NOUVEAU MODÈLE : Establishment (Établissement)
class Establishment(db.Model):
    __tablename__ = 'establishments'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # ⭐ NOUVEAU : Relations explicites pour la correction de l'erreur
    employees = db.relationship('Employee', back_populates='establishment', lazy=True)
    teams = db.relationship('Team', back_populates='establishment', lazy=True)
    
    def __repr__(self):
        return f'<Establishment {self.name}>'
