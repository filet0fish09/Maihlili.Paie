from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta
import calendar
from werkzeug.security import generate_password_hash, check_password_hash # Importez-les ici pour les méthodes

db = SQLAlchemy()

# =================================================================
# NOUVEAU MODÈLE: Establishment
# =================================================================
class Establishment(db.Model):
    __tablename__ = 'establishments'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relations inverses pour lister tous les utilisateurs/employés
    users = db.relationship('User', backref='establishment', lazy=True, foreign_keys='User.establishment_id')
    employees = db.relationship('Employee', backref='establishment', lazy=True, foreign_keys='Employee.establishment_id')

    def __repr__(self):
        return f'<Establishment {self.name}>'


# =================================================================
# MODÈLE MIS À JOUR: User
# =================================================================
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_manager = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_super_admin = db.Column(db.Boolean, default=False) # NOUVEAU: Rôle Ultra-Admin
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # NOUVEAU: Clé étrangère pour l'établissement
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=True) 
    
    # Relations
    employee = db.relationship('Employee', backref='user', uselist=False, foreign_keys='Employee.user_id')
    
    # Méthodes
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'


# =================================================================
# MODÈLE MIS À JOUR: Employee
# =================================================================
class Employee(db.Model):
    __tablename__ = 'employees'
    
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    position = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'))
    
    # NOUVEAU: Clé étrangère pour l'établissement
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=True) 
    establishment = db.relationship('Establishment', backref='employees', lazy=True) # <-- AJOUT de la relation
    
    # NOUVEAUX CHAMPS pour les heures contractuelles
    contract_hours_per_week = db.Column(db.Float, default=35.0)
    contract_hours_per_month = db.Column(db.Float, default=151.67)
    contract_type = db.Column(db.String(20), default="CDI")
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    assignments = db.relationship('Assignment', backref='employee', lazy=True, cascade='all, delete-orphan')
    managed_teams = db.relationship('Team', foreign_keys='Team.manager_id', backref='manager', lazy=True)
    
    # NOUVELLE MÉTHODE : Vérification de la gestion avec filtre d'établissement
    def can_be_managed_by(self, user):
        """Vérifie si cet employé peut être géré par l'utilisateur (manager/admin) donné, avec filtre par établissement."""
        if not user or (not user.is_manager and not user.is_super_admin and not user.is_admin):
            return False
        
        # 1. Le Super Admin peut tout gérer
        if user.is_super_admin:
            return True
            
        # 2. Vérification de l'établissement: Le manager/admin ne peut gérer que dans son établissement
        # L'Admin/Manager doit avoir un ID d'établissement, et cet ID doit correspondre à celui de l'employé
        if self.establishment_id is None or user.establishment_id is None or self.establishment_id != user.establishment_id:
            return False
            
        # 3. Logique des rôles (Admin/Manager)
        
        # L'Admin de cet établissement peut tout gérer dans cet établissement (déjà filtré en 2)
        if user.is_admin:
            return True
        
        # Si c'est un manager, vérifier les équipes
        if not user.is_manager:
            return False
            
        manager_employee = user.employee
        if not manager_employee:
            return False
            
        # Si l'employé est dans une équipe, vérifier si le manager est le responsable de cette équipe
        if self.team_id:
            # On s'assure que le manager est l'ID du manager de l'équipe
            if self.team and self.team.manager_id == manager_employee.id:
                return True
        
        # Logique pour les non-assignés (si le manager gère au moins une équipe dans cet établissement)
        managed_teams_count = Team.query.filter(
            Team.manager_id == manager_employee.id,
            Team.establishment_id == user.establishment_id # Filtre d'établissement implicite sur la Team
        ).count()
        
        # Si l'employé est non-assigné et que le manager gère des équipes, il peut le voir
        if not self.team_id and managed_teams_count > 0:
             return True

        return False

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
            # Assignment.status.in_(['completed', 'in_progress', 'scheduled']) 
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
            
        return list(reversed(history)) # Ordre chronologique

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
        return f'<Employee {self.full_name} - {self.contract_hours_per_week}h/sem

# PROPRIÉTÉ pour déterminer l'établissement actuel (favorise le lien direct si présent)
    @property
    def current_establishment(self):
        """Retourne l'établissement de l'employé, soit par lien direct, soit par son équipe."""
        if self.establishment:
            return self.establishment
        if self.team and self.team.establishment_id:
            return self.team.establishment
        return None

# =================================================================
# MODÈLE MIS À JOUR: Team
# =================================================================
class Team(db.Model):
    __tablename__ = 'teams'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    manager_id = db.Column(db.Integer, db.ForeignKey('employees.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # NOUVEAU: Clé étrangère pour l'établissement
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=True) 
    
    # Relations
    members = db.relationship('Employee', foreign_keys='Employee.team_id', backref='team', lazy=True)
    
    def __repr__(self):
        return f'<Team {self.name}>'


# =================================================================
# MODÈLE EXISTANT: Shift
# =================================================================
class Shift(db.Model):
    __tablename__ = 'shifts'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    color = db.Column(db.String(7), default='#3B82F6') # Couleur hex
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
        
        # Gérer les shifts qui traversent minuit
        if end < start:
            end += timedelta(days=1)
        
        duration = end - start
        return duration.total_seconds() / 3600
    
    def __repr__(self):
        return f'<Shift {self.name} {self.start_time}-{self.end_time}>'


# =================================================================
# MODÈLE EXISTANT: Assignment
# =================================================================
class Assignment(db.Model):
    __tablename__ = 'assignments'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    shift_id = db.Column(db.Integer, db.ForeignKey('shifts.id'), nullable=False)
    start = db.Column(db.DateTime, nullable=False)
    end = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='scheduled') # scheduled, in_progress, completed, cancelled
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # ⭐ CORRECTION : Ajouter la clé étrangère pour created_by
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Relations
    timesheet_entries = db.relationship('TimeSheetEntry', backref='assignment', lazy=True, cascade='all, delete-orphan')
    
    # ⭐ CORRECTION : Ajouter la relation vers User
    creator = db.relationship('User', backref='created_assignments', lazy=True, foreign_keys=[created_by])

    @property
    def duration_hours(self):
        """Calcule la durée de l'assignation en heures"""
        duration = self.end - self.start
        return round(duration.total_seconds() / 3600, 2)
    
    def __repr__(self):
        return f'<Assignment {self.employee_id} - {self.shift_id} on {self.start}>'

# =================================================================
# MODÈLE EXISTANT: TimeSheetEntry
# =================================================================
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
    employee = db.relationship('Employee', backref='timesheet_records', lazy=True, foreign_keys=[employee_id])
    
    @property
    def actual_duration_hours(self):
        if self.clock_out:
            duration = self.clock_out - self.clock_in
            return round(duration.total_seconds() / 3600, 2)
        return 0
        
    def __repr__(self):
        return f'<TimeSheetEntry {self.id} for Assignment {self.assignment_id}>'

