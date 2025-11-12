from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta
import calendar
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# ----------------------------------------------------------------------
# 🏰 NOUVEAU MODÈLE : Establishment (Établissement)
# ----------------------------------------------------------------------
class Establishment(db.Model):
    __tablename__ = 'establishment'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    
    # Relations : Les employés et les utilisateurs (managers/admins locaux)
    # Note : Le backref est géré dans les modèles ci-dessous.
    
    def __repr__(self):
        return f'<Establishment {self.name}>'

# ----------------------------------------------------------------------
# 👤 MODÈLE MODIFIÉ : User
# ----------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_manager = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    
    # NOUVEAU : Rôle Ultra-Administrateur (Super Admin)
    is_super_admin = db.Column(db.Boolean, default=False) 
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # NOUVEAU : Clé étrangère vers Establishment
    # Utilisé SET NULL pour ne pas supprimer un Ultra-Admin si son établissement est supprimé
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishment.id', ondelete='SET NULL'), nullable=True)
    
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
# 💼 MODÈLE MODIFIÉ : Employee
# ----------------------------------------------------------------------
class Employee(db.Model):
    __tablename__ = 'employees'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    position = db.Column(db.String(100))
    contract_hours = db.Column(db.Float, default=35.0)
    base_hourly_rate = db.Column(db.Float, default=10.0)
    is_active = db.Column(db.Boolean, default=True)
    
    # NOUVEAU : Clé étrangère vers Establishment (Doit être non nul si l'employé est actif)
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishment.id'), nullable=False)
    
    # Relations
    assignments = db.relationship('Assignment', backref='employee', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Employee {self.name}>'

# ----------------------------------------------------------------------
# 📅 MODÈLE Assignement (Pas de changement requis ici)
# ----------------------------------------------------------------------
class Assignment(db.Model):
    __tablename__ = 'assignments'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False)
    shift_id = db.Column(db.Integer, db.ForeignKey('shifts.id', ondelete='SET NULL'), nullable=True) # Set NULL si le shift est supprimé
    start = db.Column(db.DateTime, nullable=False)
    end = db.Column(db.DateTime, nullable=False)
    
    # Relation vers le shift (pour obtenir nom/couleur)
    shift = db.relationship('Shift')
    
    def duration_hours(self):
        if not self.end:
            return 0
        duration = self.end - self.start
        return round(duration.total_seconds() / 3600, 2)
    
    def __repr__(self):
        return f'<Assignment {self.employee_id} - {self.shift_id} on {self.start}>'

# ----------------------------------------------------------------------
# ⏰ NOUVEAU MODÈLE : TimeSheetEntry (Pas de changement)
# ----------------------------------------------------------------------
class TimeSheetEntry(db.Model):
    __tablename__ = 'timesheet_entries'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # CORRECTION CRUCIALE pour le DELETE 500
    assignment_id = db.Column(
        db.Integer, 
        db.ForeignKey('assignments.id', ondelete='CASCADE'), # <-- Ajout de ondelete='CASCADE'
        nullable=False
    )
    
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    
    # Heures d'arrivée/départ réelles
    clock_in = db.Column(db.DateTime, nullable=False)
    clock_out = db.Column(db.DateTime)
    
    # Type d'entrée (e.g., break, work)
    entry_type = db.Column(db.String(50), default='work') 
    
    # Relation (pour avoir accès aux données de l'employé)
    employee = db.relationship('Employee', backref='timesheet_records', lazy=True)
    
    def __repr__(self):
        return f'<TimeSheetEntry {self.employee_id} on {self.clock_in}>'

# ----------------------------------------------------------------------
# ⚙️ MODÈLES Shift et Team (Pas de changement)
# ----------------------------------------------------------------------
class Shift(db.Model):
    __tablename__ = 'shifts'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    color = db.Column(db.String(7), default='#3055ff') # Couleur hexadécimale par défaut
    
    def __repr__(self):
        return f'<Shift {self.name}>'

class Team(db.Model):
    __tablename__ = 'teams'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    # relation Many-to-Many avec Employee (voir plus bas)

employee_teams = db.Table('employee_teams',
    db.Column('employee_id', db.Integer, db.ForeignKey('employees.id'), primary_key=True),
    db.Column('team_id', db.Integer, db.ForeignKey('teams.id'), primary_key=True)
)

Employee.teams = db.relationship(
    'Team', 
    secondary=employee_teams, 
    backref=db.backref('employees', lazy='dynamic')
)

# Fin du fichier models.py
