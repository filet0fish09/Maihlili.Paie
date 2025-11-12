# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
# ⚠️ MISE À JOUR : Import de Establishment
from models import db, User, Employee, Shift, Assignment, Team, Establishment 
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
# ------------------------------------------------------------------
from datetime import datetime, timedelta
import os
from functools import wraps # ⚠️ NOUVEL IMPORT POUR LE DÉCORATEUR
# --- NOUVEAUX IMPORTS POUR L'EXPORT PDF ---
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.units import cm

# ------------------------------------------

# Définition de la couleur de branding à partir de votre logo
MAIHLILI_FOND_TABLE = colors.HexColor('#FFF0F8') # Fond du tableau (simule le fond du doc)
MAIHLILI_TITRES_BLEU = colors.HexColor('#3055FF') # Bleu pour les titres et en-têtes
MAIHLILI_BLANC = colors.white

# ... le reste du fichier app.py ...

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

# --- NOUVELLE FONCTION HELPER POUR LA RÉCUPÉRATION DES DONNÉES DE PLANNING ---
def get_gantt_data_for_week(start_date, user):
    """Récupère les données d'employés et d'assignations pour une semaine donnée."""
    manageable_employees = get_manageable_employees(user)
    manageable_ids = [emp.id for emp in manageable_employees]

    # Calculer le début de la semaine (Lundi)
    week_start = start_date - timedelta(days=start_date.weekday())
    week_end = week_start + timedelta(days=7)
    
    if manageable_ids:
        assignments_db = Assignment.query.filter(
            Assignment.employee_id.in_(manageable_ids),
            Assignment.start >= week_start,
            Assignment.start < week_end
        ).all()
    else:
        assignments_db = []

    # Formatage pour le frontend (et potentiellement le PDF)
    assignments_data = []
    for a in assignments_db:
        shift_color = a.shift.color if a.shift and a.shift.color else '#888888'
        assignments_data.append({
            'id': a.id,
            'employee_id': a.employee_id,
            'shift_name': a.shift.name if a.shift else 'N/A',
            'shift_color': shift_color,
            'start': a.start, # Format datetime.datetime
            'end': a.end,     # Format datetime.datetime
            'start_time': a.start.strftime('%H:%M'),
            'end_time': a.end.strftime('%H:%M'),
        })

    return {
        'employees': [{'id': emp.id, 'name': emp.full_name} for emp in manageable_employees],
        'assignments': assignments_data,
        'week_start': week_start,
        'week_end': week_end
    }
# --------------------------------------------------------------------------

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
        q = q.filter(Assignment.end >= datetime.fromisoformat(start_str.replace("Z", "+00:00").replace(" ", "+")))
    if end_str:
        q = q.filter(Assignment.start <= datetime.fromisoformat(end_str.replace("Z", "+00:00").replace(" ", "+")))

    events = [
    {
        "id": a.id,
            "title": f"{a.employee.full_name} - {a.shift.name}" if a.shift else f"{a.employee.full_name} - Shift",
            "start": a.start.isoformat(),
            "end": a.end.isoformat(),
            "allDay": False,
            "color": a.shift.color if a.shift else '#888888',
            "extendedProps": {
                "employee_name": a.employee.full_name,
                "shift_name": a.shift.name if a.shift else 'N/A'
            }
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
    else:
        teams = []
    
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
            print(f"ERREUR LORS DE L'ENREGISTREMENT DE L'ASSIGNATION: {e}")
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
        employee_id_str = request.form.get("employee_id")
        shift_id_str = request.form.get("shift_id") 
        start_str = request.form.get("start")
        end_str = request.form.get("end")
        notes = request.form.get("notes", "")
        
        if not all([employee_id_str, shift_id_str, start_str, end_str]):
            return jsonify({"success": False, "error": "Données manquantes"}), 400
        
        # 🚨 CORRECTION 1 : CONVERSION DES ID EN INT ICI 🚨
        try:
            employee_id = int(employee_id_str)
            shift_id = int(shift_id_str)
        except ValueError:
            print("ERREUR: Impossible de convertir l'ID en entier.")
            return jsonify({"success": False, "error": "IDs d'employé ou de service invalides"}), 400
        
        # Vérifier que le manager peut assigner cet employé (avec l'ID entier)
        employee = Employee.query.get(employee_id)
        if not employee or not employee.can_be_managed_by(current_user):
            return jsonify({"success": False, "error": "Vous ne pouvez pas assigner cet employé"}), 403
        
        start = datetime.fromisoformat(start_str.replace("Z", "+00:00").replace(" ", "+"))
        end = datetime.fromisoformat(end_str.replace("Z", "+00:00").replace(" ", "+"))
        
        assignment = Assignment(
            employee_id=employee_id, # Utiliser l'entier
            shift_id=shift_id,       # Utiliser l'entier
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
        # 🚨 CORRECTION 2 : AJOUTER LE PRINT POUR DIAGNOSTIQUER LES FUTURES ERREURS 🚨
        print(f"ERREUR CATCHED DANS L'API POST /api/assignments: {e}") 
        return jsonify({"success": False, "error": "Erreur interne lors de la création (voir logs)"}), 500

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

# Ajouter ces routes dans votre app.py après les routes existantes

# --- Route pour afficher le planning ---
@app.route("/planning")
@login_required
def planning():
    """Vue principale du planning avec calendrier et Gantt"""
    if not current_user.is_manager:
        return redirect(url_for("employee_dashboard"))
    
    return render_template("planning.html")


# --- API pour les données Gantt ---
@app.get("/api/gantt-data")
@login_required
def api_gantt_data():
    """Récupère les données pour afficher la vue Gantt"""
    start_str = request.args.get("start")
    
    # Déterminer la date de début pour le helper
    if not start_str:
        start_date = datetime.now().date()
    else:
        # Assurez-vous d'avoir une date simple pour le calcul du Lundi
        start_date = datetime.fromisoformat(start_str).date()
    
    # Utiliser le helper
    data = get_gantt_data_for_week(start_date, current_user)

    # Convertir les objets datetime en ISO string pour JSON
    assignments_json = [
        {
            **a, 
            'start': a['start'].isoformat(), 
            'end': a['end'].isoformat()
        } for a in data['assignments']
    ]
    
    return jsonify({
        "employees": data['employees'],
        "assignments": assignments_json,
        "start": data['week_start'].isoformat(),
        "end": data['week_end'].isoformat()
    })


# --- API pour les statistiques du planning ---
@app.get("/api/planning-stats")
@login_required
def api_planning_stats():
    """Récupère les statistiques du planning"""
    
    manageable_employees = get_manageable_employees(current_user)
    manageable_ids = [emp.id for emp in manageable_employees]
    
    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=7)
    
    if manageable_ids:
        week_assignments = Assignment.query.filter(
            Assignment.employee_id.in_(manageable_ids),
            Assignment.start >= week_start,
            Assignment.start < week_end
        ).all()
    else:
        week_assignments = []
    
    # Calculer les statistiques
    total_hours = sum(
        [(a.end - a.start).total_seconds() / 3600 for a in week_assignments]
    )
    
    employees_covered = len(set([a.employee_id for a in week_assignments]))
    
    # Conformité (% employés ayant des assignations)
    compliance = int((employees_covered / len(manageable_employees) * 100) if manageable_employees else 0)
    
    return jsonify({
        "assignments_week": len(week_assignments),
        "total_hours": round(total_hours, 2),
        "employees_covered": employees_covered,
        "compliance": compliance
    })


# --- NOUVELLE ROUTE POUR L'EXPORT PDF (REMPLACE LE PLACEHOLDER) ---
# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from models import db, User, Employee, Shift, Assignment, Team
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
import os
# --- NOUVEAUX IMPORTS POUR L'EXPORT PDF ---
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
# ------------------------------------------

# Définition de la couleur de branding à partir de votre logo
MAIHLILI_FOND_TABLE = colors.HexColor('#FFF0F8') # Fond du tableau (simule le fond du doc)
MAIHLILI_TITRES_BLEU = colors.HexColor('#3055FF') # Bleu pour les titres et en-têtes
MAIHLILI_BLANC = colors.white

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

# --- NOUVELLE FONCTION HELPER POUR LA RÉCUPÉRATION DES DONNÉES DE PLANNING ---
def get_gantt_data_for_week(start_date, user):
    """Récupère les données d'employés et d'assignations pour une semaine donnée."""
    manageable_employees = get_manageable_employees(user)
    manageable_ids = [emp.id for emp in manageable_employees]

    # Calculer le début de la semaine (Lundi)
    week_start = start_date - timedelta(days=start_date.weekday())
    week_end = week_start + timedelta(days=7)
    
    if manageable_ids:
        assignments_db = Assignment.query.filter(
            Assignment.employee_id.in_(manageable_ids),
            Assignment.start >= week_start,
            Assignment.start < week_end
        ).all()
    else:
        assignments_db = []

    # Formatage pour le frontend (et potentiellement le PDF)
    assignments_data = []
    for a in assignments_db:
        shift_color = a.shift.color if a.shift and a.shift.color else '#888888'
        assignments_data.append({
            'id': a.id,
            'employee_id': a.employee_id,
            'shift_name': a.shift.name if a.shift else 'N/A',
            'shift_color': shift_color,
            'start': a.start, # Format datetime.datetime
            'end': a.end,     # Format datetime.datetime
            'start_time': a.start.strftime('%H:%M'),
            'end_time': a.end.strftime('%H:%M'),
        })

    return {
        'employees': [{'id': emp.id, 'name': emp.full_name} for emp in manageable_employees],
        'assignments': assignments_data,
        'week_start': week_start,
        'week_end': week_end
    }
# --------------------------------------------------------------------------

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
        q = q.filter(Assignment.end >= datetime.fromisoformat(start_str.replace("Z", "+00:00").replace(" ", "+")))
    if end_str:
        q = q.filter(Assignment.start <= datetime.fromisoformat(end_str.replace("Z", "+00:00").replace(" ", "+")))

    events = [
    {
        "id": a.id,
            "title": f"{a.employee.full_name} - {a.shift.name}" if a.shift else f"{a.employee.full_name} - Shift",
            "start": a.start.isoformat(),
            "end": a.end.isoformat(),
            "allDay": False,
            "color": a.shift.color if a.shift else '#888888',
            "extendedProps": {
                "employee_name": a.employee.full_name,
                "shift_name": a.shift.name if a.shift else 'N/A'
            }
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
    else:
        teams = []
    
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
            print(f"ERREUR LORS DE L'ENREGISTREMENT DE L'ASSIGNATION: {e}")
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
        employee_id_str = request.form.get("employee_id")
        shift_id_str = request.form.get("shift_id") 
        start_str = request.form.get("start")
        end_str = request.form.get("end")
        notes = request.form.get("notes", "")
        
        if not all([employee_id_str, shift_id_str, start_str, end_str]):
            return jsonify({"success": False, "error": "Données manquantes"}), 400
        
        # 🚨 CORRECTION 1 : CONVERSION DES ID EN INT ICI 🚨
        try:
            employee_id = int(employee_id_str)
            shift_id = int(shift_id_str)
        except ValueError:
            print("ERREUR: Impossible de convertir l'ID en entier.")
            return jsonify({"success": False, "error": "IDs d'employé ou de service invalides"}), 400
        
        # Vérifier que le manager peut assigner cet employé (avec l'ID entier)
        employee = Employee.query.get(employee_id)
        if not employee or not employee.can_be_managed_by(current_user):
            return jsonify({"success": False, "error": "Vous ne pouvez pas assigner cet employé"}), 403
        
        start = datetime.fromisoformat(start_str.replace("Z", "+00:00").replace(" ", "+"))
        end = datetime.fromisoformat(end_str.replace("Z", "+00:00").replace(" ", "+"))
        
        assignment = Assignment(
            employee_id=employee_id, # Utiliser l'entier
            shift_id=shift_id,       # Utiliser l'entier
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
        # 🚨 CORRECTION 2 : AJOUTER LE PRINT POUR DIAGNOSTIQUER LES FUTURES ERREURS 🚨
        print(f"ERREUR CATCHED DANS L'API POST /api/assignments: {e}") 
        return jsonify({"success": False, "error": "Erreur interne lors de la création (voir logs)"}), 500

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

# Ajouter ces routes dans votre app.py après les routes existantes

# --- Route pour afficher le planning ---
@app.route("/planning")
@login_required
def planning():
    """Vue principale du planning avec calendrier et Gantt"""
    if not current_user.is_manager:
        return redirect(url_for("employee_dashboard"))
    
    return render_template("planning.html")


# --- API pour les données Gantt ---
@app.get("/api/gantt-data")
@login_required
def api_gantt_data():
    """Récupère les données pour afficher la vue Gantt"""
    start_str = request.args.get("start")
    
    # Déterminer la date de début pour le helper
    if not start_str:
        start_date = datetime.now().date()
    else:
        # Assurez-vous d'avoir une date simple pour le calcul du Lundi
        start_date = datetime.fromisoformat(start_str).date()
    
    # Utiliser le helper
    data = get_gantt_data_for_week(start_date, current_user)

    # Convertir les objets datetime en ISO string pour JSON
    assignments_json = [
        {
            **a, 
            'start': a['start'].isoformat(), 
            'end': a['end'].isoformat()
        } for a in data['assignments']
    ]
    
    return jsonify({
        "employees": data['employees'],
        "assignments": assignments_json,
        "start": data['week_start'].isoformat(),
        "end": data['week_end'].isoformat()
    })


# --- API pour les statistiques du planning ---
@app.get("/api/planning-stats")
@login_required
def api_planning_stats():
    """Récupère les statistiques du planning"""
    
    manageable_employees = get_manageable_employees(current_user)
    manageable_ids = [emp.id for emp in manageable_employees]
    
    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=7)
    
    if manageable_ids:
        week_assignments = Assignment.query.filter(
            Assignment.employee_id.in_(manageable_ids),
            Assignment.start >= week_start,
            Assignment.start < week_end
        ).all()
    else:
        week_assignments = []
    
    # Calculer les statistiques
    total_hours = sum(
        [(a.end - a.start).total_seconds() / 3600 for a in week_assignments]
    )
    
    employees_covered = len(set([a.employee_id for a in week_assignments]))
    
    # Conformité (% employés ayant des assignations)
    compliance = int((employees_covered / len(manageable_employees) * 100) if manageable_employees else 0)
    
    return jsonify({
        "assignments_week": len(week_assignments),
        "total_hours": round(total_hours, 2),
        "employees_covered": employees_covered,
        "compliance": compliance
    })


# --- NOUVELLE ROUTE POUR L'EXPORT PDF (REMPLACE LE PLACEHOLDER) ---
# NOTE: Cette fonction doit se trouver DANS votre fichier app.py
@app.route('/api/export-gantt-pdf', methods=['GET'])
@login_required
def export_gantt_pdf():
    if not current_user.is_manager:
        return jsonify({'error': 'Accès refusé'}), 403

    # --- 1. Fonction HELPER pour déterminer la couleur du texte (CORRIGÉE) ---
    def get_text_color_name(hex_color_str):
        """Détermine si le texte doit être blanc ou noir en fonction de la couleur de fond."""
        try:
            color_obj = colors.HexColor(hex_color_str)
        except: 
            color_obj = colors.HexColor('#888888') 
            
        r, g, b = color_obj.red, color_obj.green, color_obj.blue
        brightness = (r * 0.299 + g * 0.587 + b * 0.114)
        return "white" if brightness < 0.5 else "black"

    # --- 2. Préparation des dates et récupération des données ---
    start_date_str = request.args.get('start')
    if start_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    else:
        today = datetime.now().date()
        start_date = today - timedelta(days=today.weekday())

    try:
        # Assurez-vous que cette fonction est correctement importée ou définie.
        data = get_gantt_data_for_week(start_date, current_user)
        employees = data['employees']
        assignments = data['assignments']
    except NameError:
        return jsonify({'error': 'La fonction get_gantt_data_for_week est introuvable.'}), 500
    
    week_start = data['week_start']
    week_end = week_start + timedelta(days=6) # 6 jours après le début de semaine

    # --- 3. Préparation du PDF ---
    buffer = BytesIO()
    # Format Paysage (A4[1], A4[0])
    doc = SimpleDocTemplate(buffer, pagesize=(A4[1], A4[0]), leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    story = []

    # Définition des couleurs ReportLab
    MAIHLILI_TITRES_BLEU = colors.HexColor('#3055FF') 
    MAIHLILI_BLANC = colors.white
    MAIHLILI_FOND_TABLE = colors.HexColor('#F8F8F8') 

    # --- 4. En-tête (Logo et Titre) ---
    logo_path = os.path.join(app.root_path, 'static', 'images', 'maihlili-logo-light.png') 
    
    logo_element = Spacer(1, 1) 
    if os.path.exists(logo_path):
        # Logo non étiré, taille fixée
        logo_element = Image(logo_path, width=70, height=35) 
        logo_element.hAlign = 'LEFT'
        
    title_text = f"""
    <font size='18' color='{MAIHLILI_TITRES_BLEU}'><b>PLANNING HEBDOMADAIRE</b></font><br/>
    <font size='10' color='#555555'>Du {week_start.strftime('%d/%m/%Y')} au {week_end.strftime('%d/%m/%Y')}</font>
    """
    title_element = Paragraph(title_text, styles['Normal'])
    title_element.alignment = 1 # Center

    header_table = Table([[logo_element, title_element, Spacer(1, 1)]], colWidths=[70, doc.width - 140, 70])
    header_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 18)) 

    # --- 5. Préparation des données du tableau ---
    days_full = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
    
    # En-tête du planning
    header_content = [Paragraph("<b>Employé</b><br/><font size='7'>Poste</font>", styles['Normal'])]
    for i in range(7):
        current_date = week_start + timedelta(days=i)
        header_text = f"<b>{days_full[i]}</b><br/><font size='8'>{current_date.strftime('%d/%m')}</font>"
        p = Paragraph(header_text, styles['Normal'])
        p.alignment = 1 
        header_content.append(p)
    
    table_data = [header_content]

    # Structure pour regrouper les assignations par employé et par jour
    assignments_by_employee_and_day = {emp['id']: {i: [] for i in range(7)} for emp in employees}
    
    for a in assignments:
        day_of_week_index = a['start'].weekday()
        employee_id = a['employee_id']
        
        content_str = f"<b>{a['shift_name']}</b><br/>{a['start_time']}-{a['end_time']}"
        color_hex = a['shift_color']
        
        assignments_by_employee_and_day[employee_id][day_of_week_index].append((content_str, color_hex))

    # Remplissage des lignes du tableau (Gantt)
    for emp_index, emp in enumerate(employees):
        emp_name_text = f"<b>{emp['name']}</b><br/><font size='7' color='#555555'>{emp.get('position', 'Employé')}</font>"
        row = [Paragraph(emp_name_text, styles['Normal'])]
        
        emp_assignments = assignments_by_employee_and_day.get(emp['id'], {i: [] for i in range(7)})
        
        for i in range(7):
            shifts = emp_assignments[i]
            cell_content_html = []
            
            if shifts:
                for content_str, color_hex in shifts:
                    # Détermine si le texte doit être 'white' ou 'black' (chaîne)
                    text_color_name = get_text_color_name(color_hex)
                    
                    # CORRECTION MAJEURE: Obtient l'objet couleur (colors.white/colors.black)
                    text_color_obj = getattr(colors, text_color_name) 
                    
                    # CRÉATION DU STYLE STABLE: Utilise .clone()
                    p_style = styles['BodyText'].clone('ShiftBlockStyle') 
                    
                    # Appliquer les styles pour le rendu Gantt (Rectangle plein)
                    p_style.alignment = 1
                    p_style.textColor = text_color_obj
                    p_style.backColor = colors.HexColor(color_hex)
                    p_style.fontSize = 8
                    p_style.fontName = 'Helvetica'
                    p_style.borderPadding = 3 
                    p_style.borderRadius = 3 
                    
                    markup = f'{content_str}' # Ligne à l'origine du problème d'indentation
                    
                    shift_p = Paragraph(markup, p_style)
                    cell_content_html.append(shift_p)
                
                # Ajout des objets Paragraphs (les shifts) à la cellule
                row.append(cell_content_html)
            else:
                # Créer un Paragraph vide pour les cellules sans shift
                empty_p = Paragraph('', styles['BodyText'].clone('EmptyCell'))
                empty_p.alignment = 1
                row.append(empty_p) 
        
        table_data.append(row)


    # --- 6. Création et style du tableau ---
    page_width = doc.width 
    col_widths = [page_width * 0.18] + [ (page_width * 0.82) / 7 ] * 7 
    
    table = Table(table_data, colWidths=col_widths)
    
    table.setStyle(TableStyle([
        # En-tête
        ('BACKGROUND', (0, 0), (-1, 0), MAIHLILI_TITRES_BLEU), 
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        
        # Corps du tableau (Lignes alternées)
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [MAIHLILI_FOND_TABLE, MAIHLILI_BLANC]), 

        # Alignements et bordures
        ('ALIGN', (0, 0), (0, -1), 'LEFT'), 
        ('VALIGN', (0, 1), (-1, -1), 'TOP'), 
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DDDDDD')), 
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        
        # Paddings généraux
        ('LEFTPADDING', (0, 1), (0, -1), 8), 
        ('RIGHTPADDING', (0, 1), (0, -1), 4),
        ('TOPPADDING', (1, 1), (-1, -1), 6), 
        ('BOTTOMPADDING', (1, 1), (-1, -1), 6), 
        
        # Alignement des jours au centre (important pour les blocs de shift)
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'), 
    ]))

    story.append(table)

    # --- 7. Génération du document ---
    try:
        doc.build(story)
        pdf = buffer.getvalue()
        buffer.close()
        
        return pdf, 200, {
            'Content-Type': 'application/pdf',
            'Content-Disposition': f'attachment; filename="planning_maihlili_{week_start.strftime("%Y%m%d")}.pdf"'
        }
    except Exception as e:
        # Affiche l'erreur pour le débogage et retourne une erreur Flask
        print(f"Erreur lors de la construction du PDF: {e}")
        return jsonify({'error': 'Erreur lors de la construction du PDF.'}), 500

@app.route('/api/assignment/move', methods=['POST'])
@login_required
def move_assignment():
    # Vérification des droits du manager
    if not current_user.is_manager:
        return jsonify({'error': 'Accès refusé'}), 403

    data = request.get_json()
    assignment_id = data.get('assignment_id')
    new_employee_id = data.get('new_employee_id')
    new_date_str = data.get('new_date') # Format 'YYYY-MM-DD'

    if not all([assignment_id, new_employee_id, new_date_str]):
        return jsonify({'error': 'Données manquantes'}), 400

    try:
        assignment = Assignment.query.get(assignment_id)
        if not assignment:
            return jsonify({'error': 'Assignation non trouvée'}), 404
        
        # --- LOGIQUE CRITIQUE DE MISE À JOUR DE DATE/HEURE ---
        
        # 1. Calculer la durée (timedelta) du shift
        time_delta = assignment.end - assignment.start 
        
        # 2. Extraire l'heure et la minute de l'ancienne heure de début
        #    La date (jour, mois, année) sera prise de new_date_str
        old_time = assignment.start.strftime('%H:%M:%S')
        
        # 3. Créer le nouvel objet datetime de début
        new_date_start = datetime.strptime(f"{new_date_str} {old_time}", '%Y-%m-%d %H:%M:%S')
        
        # 4. Mettre à jour l'assignation dans la DB
        assignment.employee_id = new_employee_id
        assignment.start = new_date_start
        assignment.end = new_date_start + time_delta # Nouvelle fin = nouvelle heure de début + durée
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Assignation déplacée avec succès'})

    except Exception as e:
        db.session.rollback()
        # Log l'erreur pour le débogage
        print(f"Erreur lors du déplacement de l'assignation: {e}") 
        return jsonify({'error': 'Erreur serveur lors de la mise à jour'}), 500

def super_admin_required(f):
    """Décorateur pour exiger que l'utilisateur soit un Ultra-Admin."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Utilise getattr pour gérer les cas où la colonne n'existerait pas encore (avant migration)
        if not current_user.is_authenticated or not getattr(current_user, 'is_super_admin', False):
            flash("Accès refusé. Fonctionnalité réservée à l'Ultra-Administrateur.", 'error')
            return redirect(url_for('index')) 
        return f(*args, **kwargs)
    return decorated_function

# ----------------------------------------------------------------------
# 🏰 NOUVELLE ROUTE : Gestion des établissements
# ----------------------------------------------------------------------
@app.route('/super-admin/establishments', methods=['GET', 'POST'])
@login_required
@super_admin_required # Seul l'Ultra-Admin y a accès
def manage_establishments():
    establishments = Establishment.query.all()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'create':
            name = request.form.get('name')
            if name:
                if Establishment.query.filter_by(name=name).first():
                    flash(f'Un établissement nommé "{name}" existe déjà.', 'error')
                else:
                    new_est = Establishment(name=name)
                    db.session.add(new_est)
                    try:
                        db.session.commit()
                        flash(f'Établissement "{name}" créé avec succès.', 'success')
                    except Exception as e:
                        db.session.rollback()
                        flash(f'Erreur lors de la création : {e}', 'error')
            
        elif action == 'delete':
            est_id = request.form.get('establishment_id')
            est = Establishment.query.get(est_id)
            
            if est:
                try:
                    # 1. Délier les Users (les Managers/Admins locaux ne sont plus liés à cet établissement)
                    User.query.filter_by(establishment_id=est.id).update({'establishment_id': None}, synchronize_session=False)
                    
                    # 2. Supprimer les Employees (et toutes leurs dépendances via CASCADE : Assignments, TimesheetEntries)
                    # Note: Les Assignments/TimesheetEntry sont supprimés automatiquement si vous avez mis ondelete='CASCADE' dans models.py
                    Employee.query.filter_by(establishment_id=est.id).delete(synchronize_session=False)
                    
                    # 3. Supprimer l'établissement
                    db.session.delete(est)
                    db.session.commit()
                    flash(f'Établissement "{est.name}" et toutes ses données liées ont été supprimés.', 'success')
                except Exception as e:
                    db.session.rollback()
                    flash(f'Erreur lors de la suppression : {e}', 'error')

        return redirect(url_for('manage_establishments'))

    return render_template('manage_establishments.html', establishments=establishments)
# --- Lancement de l'application ---

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    
    # Configuration pour production Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)










