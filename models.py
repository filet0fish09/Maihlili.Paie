from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta
import calendar

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_manager = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    employee = db.relationship('Employee', backref='user', uselist=False)
    
    def __repr__(self):
        return f'<User {self.email}>'


class Employee(db.Model):
    __tablename__ = 'employees'
    
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    position = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'))
    
    # NOUVEAUX CHAMPS pour les heures contractuelles
    contract_hours_per_week = db.Column(db.Float, default=35.0)
    contract_hours_per_month = db.Column(db.Float, default=151.67)
    contract_type = db.Column(db.String(20), default="CDI")
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    assignments = db.relationship('Assignment', backref='employee', lazy=True, cascade='all, delete-orphan')
    managed_teams = db.relationship('Team', foreign_keys='Team.manager_id', backref='manager', lazy=True)
    
    # NOUVELLES MÉTHODES pour le calcul des heures
    
    def get_worked_hours_for_month(self, year=None, month=None):
        """Calcule les heures travaillées pour un mois donné"""
        if not year:
            year = datetime.now().year
        if not month:
            month = datetime.now().month
            
        # Premier et dernier jour du mois
        start_date = datetime(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        end_date = datetime(year, month, last_day, 23, 59, 59)
        
        # Récupérer toutes les assignations du mois
        monthly_assignments = Assignment.query.filter(
            Assignment.employee_id == self.id,
            Assignment.start >= start_date,
            Assignment.start <= end_date,
            Assignment.status.in_(['completed', 'in_progress', 'scheduled'])
        ).all()
        
        total_hours = 0
        for assignment in monthly_assignments:
            # Calculer la durée effective
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
            # Calculer le mois à analyser
            year = current_date.year
            month = current_date.month - i
            
            # Gérer le changement d'année
            while month <= 0:
                month += 12
                year -= 1
            
            target_date = datetime(year, month, 1)
            
            month_data = self.get_hours_difference_for_month(year, month)
            month_data['month'] = target_date.strftime('%B %Y')
            month_data['month_short'] = target_date.strftime('%m/%Y')
            
            history.append(month_data)
            
        return list(reversed(history))  # Ordre chronologique

    @property
    def current_month_hours_summary(self):
        """Résumé rapide du mois en cours"""
        return self.get_hours_difference_for_month()

    def update_contract_hours(self, hours_per_week):
        """Met à jour les heures contractuelles"""
        self.contract_hours_per_week = hours_per_week
        # Calculer les heures mensuelles (moyenne : 52 semaines / 12 mois)
        self.contract_hours_per_month = round(hours_per_week * 52 / 12, 2)

    def __repr__(self):
        return f'<Employee {self.full_name} - {self.contract_hours_per_week}h/sem>'


class Team(db.Model):
    __tablename__ = 'teams'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    manager_id = db.Column(db.Integer, db.ForeignKey('employees.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    members = db.relationship('Employee', foreign_keys='Employee.team_id', backref='team', lazy=True)
    
    def __repr__(self):
        return f'<Team {self.name}>'


class Shift(db.Model):
    __tablename__ = 'shifts'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    color = db.Column(db.String(7), default='#3B82F6')  # Couleur hex
    created_by = db.Column(db.Integer, db.ForeignKey('employees.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    assignments = db.relationship('Assignment', backref='shift', lazy=True)
    
    @property
    def duration_hours(self):
        """Calcule la durée du shift en heures"""
        start = datetime.combine(datetime.today(), self.start_time)
        end = datetime.combine(datetime.today(), self.end_time)
        
        # Gérer les shifts qui traversent minuit
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
    status = db.Column(db.String(20), default='scheduled')  # scheduled, in_progress, completed, cancelled
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @property
    def duration_hours(self):
        """Calcule la durée de l'assignation en heures"""
        duration = self.end - self.start
        return round(duration.total_seconds() / 3600, 2)
    
    def __repr__(self):
        return f'<Assignment {self.employee_id} - {self.shift_id} on {self.start}>'
