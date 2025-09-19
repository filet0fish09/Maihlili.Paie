from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_manager = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Relations
    employee = db.relationship("Employee", back_populates="user", uselist=False)
    created_assignments = db.relationship("Assignment", foreign_keys="Assignment.created_by", back_populates="creator")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def role_display(self):
        """Retourne l'affichage du rôle"""
        if self.is_admin:
            return "⚡ Administrateur"
        elif self.is_manager:
            return "👥 Manager"
        else:
            return "👤 Employé"

    @property
    def can_manage_employees(self):
        """Vérifie si l'utilisateur peut gérer des employés"""
        return self.is_manager or self.is_admin

    def __repr__(self):
        return f'<User {self.username}>'

class Team(db.Model):
    __tablename__ = "teams"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    manager_id = db.Column(db.Integer, db.ForeignKey("employees.id"))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    manager = db.relationship("Employee", foreign_keys=[manager_id], post_update=True)
    members = db.relationship("Employee", foreign_keys="Employee.team_id", back_populates="team")

    @property
    def member_count(self):
        """Nombre de membres actifs dans l'équipe"""
        return len([m for m in self.members if m.is_active])

    @property
    def manager_name(self):
        """Nom du manager de l'équipe"""
        return self.manager.full_name if self.manager else "Non assigné"

    def __repr__(self):
        return f'<Team {self.name}>'

class Employee(db.Model):
    __tablename__ = "employees"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    position = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    hire_date = db.Column(db.Date)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    user = db.relationship("User", back_populates="employee")
    team = db.relationship("Team", foreign_keys=[team_id], back_populates="members")
    assignments = db.relationship("Assignment", back_populates="employee", cascade="all, delete-orphan")

    @property
    def status_display(self):
        """Statut d'affichage de l'employé"""
        return "Actif" if self.is_active else "Inactif"

    @property
    def team_name(self):
        """Nom de l'équipe de l'employé"""
        return self.team.name if self.team else "Aucune équipe"

    @property
    def has_user_account(self):
        """Vérifie si l'employé a un compte utilisateur"""
        return self.user is not None

    @property
    def email(self):
        """Email de l'employé (depuis son compte utilisateur)"""
        return self.user.email if self.user else None

    def can_be_managed_by(self, manager_user):
        """Vérifie si cet employé peut être géré par ce manager"""
        if not manager_user:
            return False
            
        # Admin peut tout gérer
        if manager_user.is_admin:
            return True
            
        # Non-manager ne peut rien gérer
        if not manager_user.is_manager:
            return False
        
        manager_employee = manager_user.employee
        if not manager_employee:
            return False
        
        # Si l'employé a une équipe, vérifier si le manager gère cette équipe
        if self.team and self.team.manager_id == manager_employee.id:
            return True
            
        # Si l'employé n'a pas d'équipe, les managers peuvent le gérer
        if not self.team:
            return True
            
        return False

    def get_current_assignment(self):
        """Retourne l'assignation actuelle (en cours) de l'employé"""
        now = datetime.now()
        return Assignment.query.filter(
            Assignment.employee_id == self.id,
            Assignment.start <= now,
            Assignment.end >= now
        ).first()

    def get_next_assignment(self):
        """Retourne la prochaine assignation de l'employé"""
        now = datetime.now()
        return Assignment.query.filter(
            Assignment.employee_id == self.id,
            Assignment.start > now
        ).order_by(Assignment.start).first()

    def get_weekly_hours(self, start_date=None):
        """Calcule les heures travaillées dans la semaine"""
        if not start_date:
            from datetime import timedelta
            now = datetime.now()
            start_date = now - timedelta(days=now.weekday())
        
        end_date = start_date + timedelta(days=7)
        
        assignments = Assignment.query.filter(
            Assignment.employee_id == self.id,
            Assignment.start >= start_date,
            Assignment.start < end_date
        ).all()
        
        total_hours = 0
        for assignment in assignments:
            duration = assignment.end - assignment.start
            total_hours += duration.total_seconds() / 3600
            
        return total_hours

    def __repr__(self):
        return f'<Employee {self.full_name}>'

class Shift(db.Model):
    __tablename__ = "shifts"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    color = db.Column(db.String(7), default="#3788d8")  # Format hexadécimal
    start_time = db.Column(db.String(5), default="08:00")  # Format HH:MM
    end_time = db.Column(db.String(5), default="16:00")    # Format HH:MM
    duration_hours = db.Column(db.Float, default=8.0)      # Durée en heures
    employees_needed = db.Column(db.Integer, default=1)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    assignments = db.relationship("Assignment", back_populates="shift")

    @property
    def time_display(self):
        """Affichage formaté des horaires"""
        return f"{self.start_time} - {self.end_time}"

    @property
    def duration_display(self):
        """Affichage formaté de la durée"""
        hours = int(self.duration_hours)
        minutes = int((self.duration_hours - hours) * 60)
        if minutes > 0:
            return f"{hours}h{minutes:02d}"
        return f"{hours}h"

    def calculate_duration(self):
        """Calcule la durée basée sur start_time et end_time"""
        try:
            start_parts = self.start_time.split(':')
            end_parts = self.end_time.split(':')
            
            start_minutes = int(start_parts[0]) * 60 + int(start_parts[1])
            end_minutes = int(end_parts[0]) * 60 + int(end_parts[1])
            
            # Gérer le cas où le shift traverse minuit
            if end_minutes < start_minutes:
                end_minutes += 24 * 60
            
            duration_minutes = end_minutes - start_minutes
            self.duration_hours = duration_minutes / 60
            
        except (ValueError, IndexError):
            # En cas d'erreur, utiliser la valeur par défaut
            self.duration_hours = 8.0

    def get_current_assignments(self):
        """Retourne les assignations actuelles pour ce shift"""
        now = datetime.now()
        return Assignment.query.filter(
            Assignment.shift_id == self.id,
            Assignment.start <= now,
            Assignment.end >= now
        ).all()

    def __repr__(self):
        return f'<Shift {self.name}>'

class Assignment(db.Model):
    __tablename__ = "assignments"
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    shift_id = db.Column(db.Integer, db.ForeignKey("shifts.id"), nullable=False)
    start = db.Column(db.DateTime, nullable=False)
    end = db.Column(db.DateTime, nullable=False)
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default="scheduled")  # scheduled, in_progress, completed, cancelled
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    employee = db.relationship("Employee", back_populates="assignments")
    shift = db.relationship("Shift", back_populates="assignments")
    creator = db.relationship("User", foreign_keys=[created_by], back_populates="created_assignments")

    @property
    def duration(self):
        """Durée de l'assignation"""
        return self.end - self.start

    @property
    def duration_hours(self):
        """Durée en heures"""
        return self.duration.total_seconds() / 3600

    @property
    def duration_display(self):
        """Affichage formaté de la durée"""
        hours = self.duration_hours
        h = int(hours)
        m = int((hours - h) * 60)
        if m > 0:
            return f"{h}h{m:02d}"
        return f"{h}h"

    @property
    def status_display(self):
        """Affichage du statut"""
        status_map = {
            'scheduled': '📅 Programmé',
            'in_progress': '⏳ En cours',
            'completed': '✅ Terminé',
            'cancelled': '❌ Annulé'
        }
        return status_map.get(self.status, self.status)

    @property
    def is_current(self):
        """Vérifie si l'assignation est en cours"""
        now = datetime.now()
        return self.start <= now <= self.end

    @property
    def is_future(self):
        """Vérifie si l'assignation est dans le futur"""
        now = datetime.now()
        return self.start > now

    @property
    def is_past(self):
        """Vérifie si l'assignation est passée"""
        now = datetime.now()
        return self.end < now

    def update_status(self):
        """Met à jour automatiquement le statut basé sur les dates"""
        now = datetime.now()
        
        if self.status == 'cancelled':
            return  # Ne pas changer si déjà annulé
            
        if self.start > now:
            self.status = 'scheduled'
        elif self.start <= now <= self.end:
            self.status = 'in_progress'
        elif self.end < now:
            self.status = 'completed'

    def as_fullcalendar(self):
        """Convertit l'assignation au format FullCalendar"""
        # Mettre à jour le statut automatiquement
        self.update_status()
        
        # Couleur basée sur le statut
        color = self.shift.color
        if self.status == 'cancelled':
            color = '#dc3545'  # Rouge
        elif self.status == 'completed':
            color = '#28a745'  # Vert
        
        return {
            "id": self.id,
            "title": f"{self.shift.name} - {self.employee.full_name}",
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "color": color,
            "textColor": "#ffffff",
            "extendedProps": {
                "employee_id": self.employee_id,
                "employee_name": self.employee.full_name,
                "shift_id": self.shift_id,
                "shift_name": self.shift.name,
                "notes": self.notes,
                "status": self.status,
                "status_display": self.status_display,
                "duration": self.duration_display,
                "created_by": self.creator.username if self.creator else "Système"
            }
        }

    def check_conflicts(self):
        """Vérifie les conflits avec d'autres assignations du même employé"""
        conflicts = Assignment.query.filter(
            Assignment.employee_id == self.employee_id,
            Assignment.id != self.id,  # Exclure cette assignation
            Assignment.status != 'cancelled',
            # Vérifier les chevauchements
            db.or_(
                db.and_(Assignment.start <= self.start, Assignment.end > self.start),
                db.and__(Assignment.start < self.end, Assignment.end >= self.end),
                db.and__(Assignment.start >= self.start, Assignment.end <= self.end)
            )
        ).all()
        
        return conflicts

    def __repr__(self):
        return f'<Assignment {self.employee.full_name} - {self.shift.name} ({self.start.strftime("%d/%m/%Y %H:%M")})>'