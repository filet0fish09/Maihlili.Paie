# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from models import db, User, Employee, Shift, Assignment, Team
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
import os

app = Flask(__name__)

# Configuration pour Render avec PostgreSQL
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("SQLALCHEMY_DATABASE_URI")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "maihlili_secret_key_2024_render")

# Configuration spéciale pour Render
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_manageable_employees(user):
    """Retourne les employés qu'un manager peut gérer"""
    if user.is_admin:
        return Employee.query.filter_by(is_active=True).all()
    
    if not user.is_manager:
        return []
    
    manager_employee = user.employee
    if not manager_employee:
        return []
    
    # Employés des équipes gérées par ce manager
    managed_teams = Team.query.filter_by(manager_id=manager_employee.id).all()
    team_employees = []
    for team in managed_teams:
        team_employees.extend(team.members)
    
    # Employés sans équipe (si le manager peut les gérer)
    unassigned_employees = Employee.query.filter_by(team_id=None, is_active=True).all()
    
    all_employees = team_employees + unassigned_employees
    # Supprimer les doublons
    unique_employees = {emp.id: emp for emp in all_employees}.values()
    
    return list(unique_employees)

# --- Auth ---

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form.get("email", f"{username.lower().replace(' ', '')}@maihlili.com")
        password = request.form["password"]
        
        # Gérer les rôles
        role = request.form.get("role", "employee")
        is_manager = (role in ["manager", "admin"])
        is_admin = (role == "admin")

        if User.query.filter_by(email=email).first():
            flash("Email déjà utilisé", "error")
            return render_template("register.html")

        try:
            # Créer l'utilisateur
            user = User(username=username, email=email, is_manager=is_manager, is_admin=is_admin)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()

            # Créer automatiquement l'employé associé
            emp = Employee(full_name=username, user_id=user.id)
            db.session.add(emp)
            db.session.commit()
            
            flash("Compte créé avec succès", "success")
            return redirect(url_for("login"))
            
        except Exception as e:
            db.session.rollback()
            flash("Erreur lors de la création du compte", "error")
            return render_template("register.html")

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # On peut se connecter avec username OU email
        identifier = request.form.get("username") or request.form.get("email")
        password = request.form["password"]
        
        # Chercher l'utilisateur par username OU email
        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier)
        ).first()
            
        if user and user.check_password(password):
            # Vérifier si l'employé est actif
            if user.employee and not user.employee.is_active:
                flash("Votre compte a été désactivé. Contactez votre manager.", "error")
                return render_template("login.html")
            
            login_user(user)
            
            # Vérifier si c'est le mot de passe par défaut
            if user.check_password("maihlili123"):
                return redirect(url_for("force_password_change"))
            
            # Rediriger selon le rôle
            if user.is_manager:
                return redirect(url_for("index"))  # Dashboard manager
            else:
                return redirect(url_for("employee_dashboard"))  # Dashboard employé
        
        flash("Nom d'utilisateur/email ou mot de passe incorrect", "error")
    
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/force-password-change", methods=["GET", "POST"])
@login_required
def force_password_change():
    """Forcer le changement du mot de passe par défaut"""
    if request.method == "POST":
        current_password = request.form["current_password"]
        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]
        
        # Vérifier le mot de passe actuel
        if not current_user.check_password(current_password):
            return render_template("force_password_change.html", error="Mot de passe actuel incorrect")
        
        # Vérifier que le nouveau mot de passe n'est pas le défaut
        if new_password == "maihlili123":
            return render_template("force_password_change.html", error="Vous devez choisir un nouveau mot de passe différent")
        
        # Vérifier la confirmation
        if new_password != confirm_password:
            return render_template("force_password_change.html", error="Les mots de passe ne correspondent pas")
        
        # Vérifier la longueur minimale
        if len(new_password) < 6:
            return render_template("force_password_change.html", error="Le mot de passe doit contenir au moins 6 caractères")
        
        try:
            # Changer le mot de passe
            current_user.set_password(new_password)
            db.session.commit()
            
            flash("Mot de passe modifié avec succès", "success")
            
            # Rediriger selon le rôle
            if current_user.is_manager:
                return redirect(url_for("index"))
            else:
                return redirect(url_for("employee_dashboard"))
        except Exception as e:
            db.session.rollback()
            return render_template("force_password_change.html", error="Erreur lors du changement de mot de passe")
    
    return render_template("force_password_change.html")

# --- Dashboard Principal ---

@app.route("/")
@login_required
def index():
    if not current_user.is_manager:
        return redirect(url_for("employee_dashboard"))
    
    # Statistiques basées sur les employés gérables
    manageable_employees = get_manageable_employees(current_user)
    manageable_ids = [emp.id for emp in manageable_employees]
    
    total_employees = len(manageable_employees)
    total_shifts_today = Shift.query.count()
    
    # Assignations de cette semaine pour les employés gérables
    week_start = datetime.now() - timedelta(days=datetime.now().weekday())
    week_assignments = Assignment.query.filter(
        Assignment.employee_id.in_(manageable_ids) if manageable_ids else Assignment.id == -1,
        Assignment.start >= week_start
    ).all()
    
    total_hours = sum([(a.end - a.start).total_seconds() / 3600 for a in week_assignments])
    conflicts = 0
    
    # Ajouter les shifts pour le modal
    shifts = Shift.query.all()
    
    return render_template("index.html", 
                         total_employees=total_employees,
                         total_shifts_today=len(week_assignments),
                         total_hours=int(total_hours),
                         conflicts=conflicts,
                         manageable_employees=manageable_employees,
                         shifts=shifts)

# --- Dashboard Employé ---

@app.route("/employee-dashboard")
@login_required
def employee_dashboard():
    if current_user.is_manager:
        return redirect(url_for("index"))
    
    # Récupérer seulement les assignations de cet employé
    employee = current_user.employee
    if not employee:
        flash("Profil employé non trouvé", "error")
        return redirect(url_for("login"))
    
    my_assignments = Assignment.query.filter_by(employee_id=employee.id).order_by(Assignment.start.desc()).all()
    
    # Statistiques de l'employé
    total_hours_week = 0
    assignments_week = 0
    next_shift = None
    
    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    
    for assignment in my_assignments:
        if assignment.start >= week_start:
            assignments_week += 1
            duration = assignment.end - assignment.start
            total_hours_week += duration.total_seconds() / 3600
        
        # Prochain shift
        if assignment.start > now and (not next_shift or assignment.start < next_shift.start):
            next_shift = assignment
    
    return render_template("employee_dashboard.html", 
                         assignments=my_assignments,
                         employee=employee,
                         total_hours_week=int(total_hours_week),
                         assignments_week=assignments_week,
                         next_shift=next_shift)

# --- API Événements --- CORRIGÉ

@app.get("/api/assignments/events")  # Route corrigée
@login_required
def api_events():
    start_str = request.args.get("start")
    end_str = request.args.get("end")
    
    if current_user.is_manager:
        # Manager : voir les assignations de ses employés
        manageable_employees = get_manageable_employees(current_user)
        manageable_ids = [emp.id for emp in manageable_employees]
        if manageable_ids:
            q = Assignment.query.filter(Assignment.employee_id.in_(manageable_ids))
        else:
            return jsonify([])
    else:
        # Employé : voir seulement ses assignations
        emp = current_user.employee
        if not emp:
            return jsonify([])
        q = Assignment.query.filter(Assignment.employee_id == emp.id)

    if start_str:
        q = q.filter(Assignment.end >= datetime.fromisoformat(start_str.replace("Z", "+00:00")))
    if end_str:
        q = q.filter(Assignment.start <= datetime.fromisoformat(end_str.replace("Z", "+00:00")))

    events = [
    {
        "id": a.id,
        "title": getattr(a, "title", "Affectation"),
        "start": a.start_date.isoformat() if a.start_date else None,
        "end": a.end_date.isoformat() if a.end_date else None,
        "allDay": False,
    }
    for a in q.all()
]

    return jsonify(events)

# --- CRUD Employés ---
@app.route("/employees", methods=["GET", "POST"])
@login_required
def show_employees():
    if not current_user.is_manager:
        flash("Accès refusé", "error")
        return redirect(url_for("index"))
        
    if request.method == "POST":
        name = request.form["full_name"]
        position = request.form.get("position")
        email = request.form.get("email")
        team_id = request.form.get("team_id")
        create_account = "create_account" in request.form
        
        try:
            # NOUVEAU : Récupérer les heures contractuelles
            contract_hours = float(request.form.get("contract_hours", 35.0))
            contract_type = request.form.get("contract_type", "CDI")
            
            # Créer l'employé
            emp = Employee(
                full_name=name, 
                position=position,
                team_id=int(team_id) if team_id else None,
                contract_hours_per_week=contract_hours,
                contract_type=contract_type
            )
            emp.update_contract_hours(contract_hours)
            
            # Créer un compte utilisateur si demandé et email fourni
            if create_account and email:
                # Vérifier que l'email n'existe pas
                if User.query.filter_by(email=email).first():
                    flash("Un compte avec cet email existe déjà", "error")
                    return redirect(url_for("show_employees"))
                
                # Créer le nom d'utilisateur
                username = name.lower().replace(' ', '.').replace('é', 'e').replace('è', 'e').replace('à', 'a')
                counter = 1
                original_username = username
                
                while User.query.filter_by(username=username).first():
                    username = f"{original_username}{counter}"
                    counter += 1
                
                # Créer l'utilisateur
                user = User(
                    username=username,
                    email=email,
                    is_manager=False,
                    is_admin=False
                )
                user.set_password("maihlili123")
                db.session.add(user)
                db.session.flush()
                emp.user_id = user.id
                
                flash(f"Employé créé avec compte utilisateur (nom d'utilisateur: {username})", "success")
            else:
                flash("Employé créé avec succès", "success")
            
            db.session.add(emp)
            db.session.commit()
            
            return redirect(url_for("show_employees"))
            
        except Exception as e:
            db.session.rollback()
            flash("Erreur lors de la création de l'employé", "error")
            return redirect(url_for("show_employees"))
    
    # GET: Afficher seulement les employés gérables
    employees = get_manageable_employees(current_user)
    
    # Ajouter des attributs pour l'affichage
    for e in employees:
        e.avatar = 'USER'
        e.role = e.position or 'Employe'
        e.status = 'active' if e.is_active else 'absent'
        e.hours_summary = e.current_month_hours_summary
        
    # Équipes disponibles pour ce manager
    teams = []
    if current_user.is_admin:
        teams = Team.query.all()
    elif current_user.employee:
        teams = Team.query.filter_by(manager_id=current_user.employee.id).all()
    
    return render_template("employees.html", employees=employees, teams=teams)

# --- CRUD Shifts ---

@app.route("/shifts", methods=["GET", "POST"])
@login_required
def show_shifts():
    if not current_user.is_manager:
        flash("Accès refusé", "error")
        return redirect(url_for("index"))
        
    if request.method == "POST":
        name = request.form["name"]
        color = request.form.get("color", "#3788d8")
        start_time = request.form.get("start_time", "08:00")
        end_time = request.form.get("end_time", "16:00")
        
        try:
            shift = Shift(
                name=name, 
                color=color,
                start_time=start_time,
                end_time=end_time
            )
            db.session.add(shift)
            db.session.commit()
            flash("Service créé avec succès", "success")
        except Exception as e:
            db.session.rollback()
            flash("Erreur lors de la création du service", "error")
        
    shifts = Shift.query.all()
    
    # Ajouter des attributs pour l'affichage
    for s in shifts:
        if not hasattr(s, 'time'):
            s.time = f"{s.start_time or '08:00'}-{s.end_time or '16:00'}"
        if not hasattr(s, 'employees_needed'):
            s.employees_needed = s.employees_needed or 3
        
    return render_template("shifts.html", shifts=shifts)

@app.route("/api/shifts/<int:shift_id>", methods=["DELETE"])
@login_required
def delete_shift(shift_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    try:
        shift = Shift.query.get_or_404(shift_id)
        db.session.delete(shift)
        db.session.commit()
        
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": "Erreur lors de la suppression"}), 500

@app.route("/api/shifts/<int:shift_id>", methods=["PUT"])
@login_required
def update_shift(shift_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    try:
        shift = Shift.query.get_or_404(shift_id)
        
        shift.name = request.form.get("name", shift.name)
        shift.color = request.form.get("color", shift.color)
        shift.start_time = request.form.get("start_time", shift.start_time)
        shift.end_time = request.form.get("end_time", shift.end_time)
        
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": "Erreur lors de la modification"}), 500

# --- Gestion des Équipes ---

@app.route("/teams", methods=["GET", "POST"])
@login_required
def manage_teams():
    if not current_user.is_manager:
        flash("Accès refusé", "error")
        return redirect(url_for("index"))
        
    if request.method == "POST":
        name = request.form["name"]
        description = request.form.get("description", "")
        
        try:
            team = Team(
                name=name,
                description=description,
                manager_id=current_user.employee.id if current_user.employee else None
            )
            db.session.add(team)
            db.session.commit()
            flash("Équipe créée avec succès", "success")
        except Exception as e:
            db.session.rollback()
            flash("Erreur lors de la création de l'équipe", "error")
    
    # Afficher les équipes gérées
    if current_user.is_admin:
        teams = Team.query.all()
    elif current_user.employee:
        teams = Team.query.filter_by(manager_id=current_user.employee.id).all()
    else:
        teams = []
    
    return render_template("teams.html", teams=teams)

@app.route("/api/teams/<int:team_id>", methods=["DELETE"])
@login_required
def delete_team(team_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    try:
        team = Team.query.get_or_404(team_id)
        
        # Vérifier les permissions
        if not current_user.is_admin and team.manager_id != current_user.employee.id:
            return jsonify({"success": False, "error": "Vous ne pouvez pas supprimer cette équipe"}), 403
        
        # Retirer les employés de l'équipe avant de la supprimer
        for member in team.members:
            member.team_id = None
        
        db.session.delete(team)
        db.session.commit()
        
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": "Erreur lors de la suppression"}), 500

@app.route("/api/unassigned-employees")
@login_required
def get_unassigned_employees():
    if not current_user.is_manager:
        return jsonify([])
    
    # Employés sans équipe que le manager peut gérer
    manageable_employees = get_manageable_employees(current_user)
    unassigned = [emp for emp in manageable_employees if not emp.team_id]
    
    return jsonify([{
        "id": emp.id,
        "full_name": emp.full_name,
        "position": emp.position
    } for emp in unassigned])

@app.route("/api/teams/<int:team_id>/assign", methods=["POST"])
@login_required
def assign_employees_to_team(team_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    try:
        team = Team.query.get_or_404(team_id)
        
        # Vérifier les permissions
        if not current_user.is_admin and team.manager_id != current_user.employee.id:
            return jsonify({"success": False, "error": "Vous ne pouvez pas modifier cette équipe"}), 403
        
        data = request.get_json()
        employee_ids = data.get("employee_ids", [])
        
        for emp_id in employee_ids:
            employee = Employee.query.get(emp_id)
            if employee and employee.can_be_managed_by(current_user):
                employee.team_id = team_id
        
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": "Erreur lors de l'assignation"}), 500

@app.route("/api/teams/<int:team_id>/remove/<int:employee_id>", methods=["POST"])
@login_required
def remove_employee_from_team(team_id, employee_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    try:
        employee = Employee.query.get_or_404(employee_id)
        
        if not employee.can_be_managed_by(current_user):
            return jsonify({"success": False, "error": "Vous ne pouvez pas modifier cet employé"}), 403
        
        employee.team_id = None
        db.session.commit()
        
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": "Erreur lors de la modification"}), 500

# --- Assignations ---

@app.route("/assignments", methods=["GET", "POST"])
@login_required
def assignments():
    if not current_user.is_manager:
        flash("Accès refusé", "error")
        return redirect(url_for("index"))
        
    if request.method == "POST":
        employee_id = request.form["employee_id"]
        shift_id = request.form["shift_id"]
        start_date = request.form["start_date"]
        start_time = request.form["start_time"]
        end_date = request.form["end_date"]
        end_time = request.form["end_time"]
        notes = request.form.get("notes", "")
        
        try:
            # Vérifier que le manager peut assigner cet employé
            employee = Employee.query.get(employee_id)
            if not employee or not employee.can_be_managed_by(current_user):
                flash("Vous ne pouvez pas assigner cet employé", "error")
                return redirect(url_for("assignments"))
            
            start = datetime.strptime(f"{start_date} {start_time}", "%Y-%m-%d %H:%M")
            end = datetime.strptime(f"{end_date} {end_time}", "%Y-%m-%d %H:%M")
            
            assignment = Assignment(
                employee_id=employee_id,
                shift_id=shift_id,
                start=start,
                end=end,
                notes=notes,
                created_by=current_user.id
            )
            
            db.session.add(assignment)
            db.session.commit()
            
            flash("Assignation créée avec succès", "success")
            return redirect(url_for("assignments"))
            
        except Exception as e:
            db.session.rollback()
            flash("Erreur lors de la création de l'assignation", "error")
            return redirect(url_for("assignments"))
    
    # Afficher seulement les assignations des employés gérables
    manageable_employees = get_manageable_employees(current_user)
    manageable_ids = [emp.id for emp in manageable_employees]
    
    if manageable_ids:
        assignments = Assignment.query.filter(
            Assignment.employee_id.in_(manageable_ids)
        ).order_by(Assignment.start.desc()).all()
    else:
        assignments = []
    
    shifts = Shift.query.all()
    
    # Calculer les statistiques pour le template
    assignments_today = 0
    assignments_week = 0
    conflicts = 0
    
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    week_start = now - timedelta(days=now.weekday())
    
    for assignment in assignments:
        if today_start <= assignment.start < today_end:
            assignments_today += 1
        if assignment.start >= week_start:
            assignments_week += 1
    
    return render_template("assignments.html", 
                         assignments=assignments,
                         employees=manageable_employees, 
                         shifts=shifts,
                         assignments_today=assignments_today,
                         assignments_week=assignments_week,
                         conflicts=conflicts)

@app.route("/api/assignments", methods=["POST"])
@login_required
def create_assignment():
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    try:
        employee_id = request.form.get("employee_id")
        shift_id = request.form.get("shift_id") 
        start_str = request.form.get("start")
        end_str = request.form.get("end")
        notes = request.form.get("notes", "")
        
        if not all([employee_id, shift_id, start_str, end_str]):
            return jsonify({"success": False, "error": "Données manquantes"}), 400
        
        # Vérifier que le manager peut assigner cet employé
        employee = Employee.query.get(employee_id)
        if not employee or not employee.can_be_managed_by(current_user):
            return jsonify({"success": False, "error": "Vous ne pouvez pas assigner cet employé"}), 403
        
        start = datetime.fromisoformat(start_str.replace('T', ' '))
        end = datetime.fromisoformat(end_str.replace('T', ' '))
        
        assignment = Assignment(
            employee_id=int(employee_id),
            shift_id=int(shift_id),
            start=start,
            end=end,
            notes=notes,
            created_by=current_user.id
        )
        
        db.session.add(assignment)
        db.session.commit()
        
        return jsonify({"success": True})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": "Erreur lors de la création"}), 500

@app.route("/api/assignments/<int:assignment_id>", methods=["PUT"])
@login_required
def update_assignment(assignment_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    try:
        assignment = Assignment.query.get_or_404(assignment_id)
        
        # Vérifier que le manager peut modifier cette assignation
        if not assignment.employee.can_be_managed_by(current_user):
            return jsonify({"success": False, "error": "Vous ne pouvez pas modifier cette assignation"}), 403
        
        data = request.get_json()
        
        if 'start' in data:
            assignment.start = datetime.fromisoformat(data['start'].replace('Z', ''))
        if 'end' in data:
            assignment.end = datetime.fromisoformat(data['end'].replace('Z', ''))
            
        db.session.commit()
        
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": "Erreur lors de la mise à jour"}), 500

@app.route("/api/assignments/<int:assignment_id>", methods=["DELETE"])
@login_required
def delete_assignment(assignment_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    try:
        assignment = Assignment.query.get_or_404(assignment_id)
        
        # Vérifier que le manager peut supprimer cette assignation
        if not assignment.employee.can_be_managed_by(current_user):
            return jsonify({"success": False, "error": "Vous ne pouvez pas supprimer cette assignation"}), 403
        
        db.session.delete(assignment)
        db.session.commit()
        
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": "Erreur lors de la suppression"}), 500

@app.route("/api/assignments/<int:assignment_id>/duplicate", methods=["POST"])
@login_required
def duplicate_assignment(assignment_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    try:
        original = Assignment.query.get_or_404(assignment_id)
        
        # Vérifier les permissions
        if not original.employee.can_be_managed_by(current_user):
            return jsonify({"success": False, "error": "Vous ne pouvez pas dupliquer cette assignation"}), 403
        
        # Créer une nouvelle assignation basée sur l'originale
        duplicate = Assignment(
            employee_id=original.employee_id,
            shift_id=original.shift_id,
            start=original.start + timedelta(days=7),  # Décaler d'une semaine
            end=original.end + timedelta(days=7),
            notes=original.notes,
            created_by=current_user.id
        )
        
        db.session.add(duplicate)
        db.session.commit()
        
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": "Erreur lors de la duplication"}), 500
# ========== NOUVELLES ROUTES POUR LES HEURES CONTRACTUELLES ==========

@app.route("/employees/<int:employee_id>/hours")
@login_required
def employee_hours_detail(employee_id):
    if not current_user.is_manager:
        flash("Accès refusé", "error")
        return redirect(url_for("index"))
    
    employee = Employee.query.get_or_404(employee_id)
    
    # Vérifier que le manager peut voir cet employé
    if not employee.can_be_managed_by(current_user):
        flash("Vous ne pouvez pas consulter cet employé", "error")
        return redirect(url_for("show_employees"))
    
    months_history = employee.get_monthly_hours_history(6)
    current_month = employee.current_month_hours_summary
    
    return render_template("employee_hours_detail.html",
                         employee=employee,
                         months_history=months_history,
                         current_month=current_month)

@app.route("/api/employees/<int:employee_id>/contract", methods=["PUT"])
@login_required
def update_employee_contract(employee_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    employee = Employee.query.get_or_404(employee_id)
    
    if not employee.can_be_managed_by(current_user):
        return jsonify({"success": False, "error": "Non autorisé"}), 403
    
    try:
        data = request.get_json()
        hours_per_week = float(data.get("hours_per_week", employee.contract_hours_per_week))
        contract_type = data.get("contract_type", employee.contract_type)
        
        employee.contract_hours_per_week = hours_per_week
        employee.contract_type = contract_type
        employee.update_contract_hours(hours_per_week)
        
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/hours-stats")
@login_required
def get_hours_stats():
    if not current_user.is_manager:
        return jsonify({"error": "Accès refusé"}), 403
    
    manageable_employees = get_manageable_employees(current_user)
    
    total_over_hours = 0
    total_under_hours = 0
    employees_over = 0
    employees_under = 0
    
    for emp in manageable_employees:
        hours_data = emp.current_month_hours_summary
        diff = hours_data['difference']
        
        if diff > 0:
            total_over_hours += diff
            employees_over += 1
        elif diff < 0:
            total_under_hours += abs(diff)
            employees_under += 1
    
    return jsonify({
        "total_over_hours": round(total_over_hours, 2),
        "total_under_hours": round(total_under_hours, 2),
        "employees_over": employees_over,
        "employees_under": employees_under,
        "total_employees": len(manageable_employees)
    })

@app.route("/api/employees-attention")
@login_required
def get_attention_employees():
    if not current_user.is_manager:
        return jsonify({"error": "Accès refusé"}), 403
    
    manageable_employees = get_manageable_employees(current_user)
    attention_list = []
    
    for emp in manageable_employees:
        hours_data = emp.current_month_hours_summary
        diff = abs(hours_data['difference'])
        
        if diff > 10:
            attention_list.append({
                "id": emp.id,
                "name": emp.full_name,
                "position": emp.position,
                "difference": hours_data['difference'],
                "status": hours_data['status']
            })
    
    attention_list.sort(key=lambda x: abs(x['difference']), reverse=True)
    return jsonify(attention_list)

# --- Paramètres ---

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        # Gestion changement de mot de passe
        if 'current_password' in request.form:
            current_password = request.form["current_password"]
            new_password = request.form["new_password"]
            confirm_password = request.form["confirm_password"]
            
            # Vérifier le mot de passe actuel
            if not current_user.check_password(current_password):
                flash("Mot de passe actuel incorrect", "error")
                return redirect(url_for("settings"))
            
            # Vérifier que les nouveaux mots de passe correspondent
            if new_password != confirm_password:
                flash("Les mots de passe ne correspondent pas", "error")
                return redirect(url_for("settings"))
            
            if len(new_password) < 6:
                flash("Le mot de passe doit contenir au moins 6 caractères", "error")
                return redirect(url_for("settings"))
            
            try:
                # Changer le mot de passe
                current_user.set_password(new_password)
                db.session.commit()
                flash("Mot de passe changé avec succès", "success")
            except Exception as e:
                db.session.rollback()
                flash("Erreur lors du changement de mot de passe", "error")
                
        # Gestion modification profil
        elif 'username' in request.form:
            username = request.form.get("username")
            email = request.form.get("email")
            
            if username and username != current_user.username:
                # Vérifier unicité
                if User.query.filter_by(username=username).first():
                    flash("Ce nom d'utilisateur est déjà pris", "error")
                else:
                    current_user.username = username
            
            if email and email != current_user.email:
                # Vérifier unicité
                if User.query.filter_by(email=email).first():
                    flash("Cet email est déjà utilisé", "error")
                else:
                    current_user.email = email
            
            try:
                db.session.commit()
                flash("Profil mis à jour avec succès", "success")
            except Exception as e:
                db.session.rollback()
                flash("Erreur lors de la mise à jour", "error")
                
        return redirect(url_for("settings"))
    
    return render_template("settings.html")

# --- Export CSV ---

@app.route("/export/week")
@login_required
def export_week():
    if not current_user.is_manager:
        flash("Accès refusé", "error")
        return redirect(url_for("index"))
        
    import csv
    from io import StringIO
    
    # Exporter seulement les assignations des employés gérables
    manageable_employees = get_manageable_employees(current_user)
    manageable_ids = [emp.id for emp in manageable_employees]
    
    if manageable_ids:
        assignments = Assignment.query.filter(Assignment.employee_id.in_(manageable_ids)).all()
    else:
        assignments = []
    
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["Employee", "Shift", "Start", "End", "Duration"])
    
    for a in assignments:
        duration = a.end - a.start
        writer.writerow([
            a.employee.full_name, 
            a.shift.name, 
            a.start.strftime('%d/%m/%Y %H:%M'), 
            a.end.strftime('%d/%m/%Y %H:%M'),
            f"{duration.total_seconds() / 3600:.1f}h"
        ])
    
    si.seek(0)
    return si.getvalue(), 200, {
        'Content-Type': 'text/csv', 
        'Content-Disposition': 'attachment; filename="planning_maihlili_spv.csv"'
    }

# --- Gestion des erreurs ---

@app.errorhandler(404)
def not_found_error(error):
    return """
    <html>
        <head><title>Page non trouvée</title></head>
        <body>
            <h1>Erreur 404</h1>
            <p>La page que vous cherchez n'existe pas.</p>
            <a href="/">Retour à l'accueil</a>
        </body>
    </html>
    """, 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return """
    <html>
        <head><title>Erreur interne</title></head>
        <body>
            <h1>Erreur 500</h1>
            <p>Une erreur interne s'est produite.</p>
            <a href="/">Retour à l'accueil</a>
        </body>
    </html>
    """, 500

# --- Lancement de l'application ---

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    
    # Configuration pour production Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)



