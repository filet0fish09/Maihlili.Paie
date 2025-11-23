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
from reportlab.lib.styles import getSampleStyleSheet      # ✅ CORRIGÉ
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.units import cm
from functools import wraps

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


# =================================================================
# NOUVELLES FONCTIONS HELPER (Sécurité des Établissements)
# =================================================================

def get_current_establishment_id():
    """Récupère l'ID de l'établissement de l'utilisateur connecté."""
    if current_user.is_authenticated and hasattr(current_user, 'establishment_id') and current_user.establishment_id:
        return current_user.establishment_id
    return None 

def manager_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # La condition vérifie si l'utilisateur est manager OU admin OU super_admin
        if not current_user.is_manager and not current_user.is_admin and not current_user.is_super_admin:
            flash('Accès refusé. Cette page nécessite des droits de manager ou d\'administrateur.', 'warning')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def get_manageable_employees(user):
    """Retourne les employés qu'un manager peut gérer, FILTRÉS PAR ÉTABLISSEMENT."""
    
    # 1. Ultra-Admin voit tout (tous les employés actifs)
    if hasattr(user, 'is_super_admin') and user.is_super_admin:
        return Employee.query.filter_by(is_active=True).all()
        
    # --- FILTRE D'ÉTABLISSEMENT OBLIGATOIRE POUR LES AUTRES RÔLES ---
    est_id = get_current_establishment_id()
    if est_id is None:
        # L'utilisateur doit être lié à un établissement pour voir les données
        return []

    # Requête de base : employés ACTIFS de l'établissement COURANT
    base_query = Employee.query.filter_by(is_active=True, establishment_id=est_id)

    if user.is_admin:
        # L'Admin de cet établissement voit TOUS les employés actifs de CET établissement
        return base_query.all()
    
    # Si ce n'est pas un Manager, ne retourne rien (hors Admin/SuperAdmin)
    if not user.is_manager:
        return []
        
    # Logique pour les Managers (qui ne voient que leurs équipes ou les non-assignés)
    manager_employee = user.employee
    if not manager_employee:
        return []
    
    # Filtrer les équipes gérées par ce manager
    managed_teams = Team.query.filter_by(manager_id=manager_employee.id).all()
    
    all_employees = []
    
    # 1. Employés dans les équipes gérées par ce manager ET dans l'établissement
    for team in managed_teams:
        # On utilise la base_query pour garantir le filtre par établissement
        all_employees.extend(base_query.filter_by(team_id=team.id).all())
        
    # 2. Employés sans équipe (non-assignés) de cet établissement
    unassigned_employees = base_query.filter_by(team_id=None).all()
    
    all_employees.extend(unassigned_employees)
    
    # Supprimer les doublons
    unique_employees = {emp.id: emp for emp in all_employees}.values()
    
    return list(unique_employees)
    
# --------------------------------------------------------------------------

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

# --- Auth (Mise à jour de la route /register) ---

@app.route("/register", methods=["GET", "POST"])
# Dans app.py - NOUVELLE VERSION DE LA ROUTE REGISTER
@app.route('/register', methods=['GET', 'POST'])
def register():
    # Récupérer la liste des établissements pour le formulaire
    establishments = Establishment.query.all() 
    
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        establishment_id = request.form.get('establishment_id') # Récupérer l'établissement
        magic_word = request.form.get('magic_word') # Mot de passe spécial

        # Vérification d'unicité
        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash('Ce nom d\'utilisateur ou cet email est déjà pris.', 'error')
            return redirect(url_for('register'))

        # Rôles par défaut
        is_admin = False
        is_manager = False
        
        # ⭐ VÉRIFICATION DU MOT DE PASSE MAGIQUE
        MAGIC_PASSWORD = "Toulouse@2026+" 
        
        if magic_word == MAGIC_PASSWORD:
            is_admin = request.form.get('is_admin') == 'on'
            is_manager = request.form.get('is_manager') == 'on'
        
        # Gérer l'établissement_id: None si non sélectionné
        final_establishment_id = int(establishment_id) if establishment_id else None

        new_user = User(
            username=username,
            email=email,
            is_admin=is_admin,
            is_manager=is_manager,
            is_super_admin=False, # Les Super Admin ne peuvent pas être créés par register
            establishment_id=final_establishment_id # Assignation de l'établissement
        )
        new_user.set_password(password)
        
        try:
            db.session.add(new_user)
            db.session.commit()
            
            # ⭐ CRÉATION AUTOMATIQUE D'EMPLOYEE
            # Un utilisateur lié à un établissement doit être un employé
            if final_establishment_id:
                 new_employee = Employee(
                    full_name=username,
                    user_id=new_user.id,
                    establishment_id=final_establishment_id,
                    position="Manager" if is_manager else "Employé"
                )
                 db.session.add(new_employee)
                 db.session.commit()
                 
            flash('Compte créé avec succès. Vous pouvez vous connecter.', 'success')
            return redirect(url_for('login'))
        
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la création du compte : {e}', 'error')

    return render_template('register.html', establishments=establishments)
    
# =================================================================
# NOUVELLE ROUTE : Ultra-Admin (Gestion Établissements)
# =================================================================
@app.route('/super-admin/establishments', methods=['GET', 'POST'])
@login_required
def manage_establishments():
    """Permet à l'Ultra-Admin de créer et lister/supprimer les établissements."""
    
    # 1. Sécurité: Seul l'Ultra-Admin a accès
    if not hasattr(current_user, 'is_super_admin') or not current_user.is_super_admin:
        flash("Accès refusé. Vous devez être Ultra-Administrateur.", "error")
        return redirect(url_for('index')) # Redirection vers le dashboard

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'create':
            name = request.form.get('name')
            if not name:
                flash("Le nom de l'établissement est requis.", "error")
                return redirect(url_for('manage_establishments'))
                
            new_establishment = Establishment(name=name)
            db.session.add(new_establishment)
            try:
                db.session.commit()
                flash(f"L'établissement '{name}' a été créé avec succès (ID: {new_establishment.id}).", "success")
            except Exception as e:
                db.session.rollback()
                flash(f"Erreur lors de la création: {e}", "error")
        
        elif action == 'delete':
            est_id = request.form.get('establishment_id')
            if not est_id:
                flash("ID d'établissement manquant pour la suppression.", "error")
                return redirect(url_for('manage_establishments'))
            
            est = Establishment.query.get(int(est_id))
            if est:
                try:
                    # Logique de suppression en cascade pour éviter les erreurs de clés étrangères
                    # 1. Délier les Users (les Managers/Admins locaux ne sont plus liés à cet établissement)
                    User.query.filter_by(establishment_id=est.id).update({'establishment_id': None}, synchronize_session=False)
                    
                    # 2. Supprimer les Employees (et toutes leurs dépendances via CASCADE : Assignments, TimesheetEntries)
                    Employee.query.filter_by(establishment_id=est.id).delete(synchronize_session=False)
                    
                    # 3. Supprimer l'établissement
                    db.session.delete(est)
                    db.session.commit()
                    flash(f"Établissement '{est.name}' et toutes ses données liées ont été supprimés.", "success")
                except Exception as e:
                    db.session.rollback()
                    flash(f"Erreur lors de la suppression : {e}", "error")

        return redirect(url_for('manage_establishments'))

    establishments = Establishment.query.all()
    # Pour l'affichage, on ajoute le nombre d'utilisateurs liés
    for est in establishments:
         est.user_count = User.query.filter_by(establishment_id=est.id).count()
         
    return render_template('manage_establishments.html', establishments=establishments)


# --- Reste des routes ---

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
            if user.is_manager or user.is_super_admin: # Ajout Super Admin
                return redirect(url_for("index"))  # Dashboard manager/admin
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
            if current_user.is_manager or current_user.is_super_admin: # Ajout Super Admin
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
    if not current_user.is_manager and not current_user.is_super_admin: # Ajout Super Admin
        return redirect(url_for("employee_dashboard"))
    
    # S'assurer que le manager est lié à un établissement s'il n'est pas Super Admin
    if not current_user.is_super_admin and get_current_establishment_id() is None:
        flash("Vous n'êtes pas lié à un établissement. Contactez un Ultra-Admin.", "error")
        return redirect(url_for("logout")) # Déconnexion pour forcer l'Admin à corriger
    
    # Statistiques basées sur les employés gérables
    manageable_employees = get_manageable_employees(current_user)
    manageable_ids = [emp.id for emp in manageable_employees]
    
    total_employees = len(manageable_employees)
    # Dans une application multi-établissement, on ne peut pas compter les shifts globaux,
    # car les Shifts devraient être liés à l'établissement ou être globaux pour l'Admin/Manager.
    # On va laisser le compte total pour l'instant, mais la donnée n'est plus pertinente.
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
# ... (inchangé, car il filtre sur current_user.employee.id) ...

@app.route("/employee-dashboard")
@login_required
def employee_dashboard():
    if current_user.is_manager or current_user.is_super_admin:
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

# --- API Événements --- (Fonctionne avec le nouveau get_manageable_employees)
@app.get("/api/assignments/events")  
@login_required
def api_events():
    start_str = request.args.get("start")
    end_str = request.args.get("end")
    
    if current_user.is_manager or current_user.is_super_admin:
        # Manager/Super Admin : voir les assignations de ses employés
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
    

# --- CRUD Employés (Mise à jour pour l'établissement) ---
@app.route("/employees", methods=["GET", "POST"])
@login_required
def show_employees():
    if not (current_user.is_manager or current_user.is_super_admin):
        flash("Accès refusé", "error")
        return redirect(url_for("index"))
        
    if request.method == "POST":
        name = request.form["full_name"]
        position = request.form.get("position")
        email = request.form.get("email")
        team_id = request.form.get("team_id")
        
        # NOUVEAU : Récupérer l'ID de l'établissement
        establishment_id = request.form.get("establishment_id")
        
        create_account = "create_account" in request.form
        
        try:
            # Récupérer les heures contractuelles
            contract_hours = float(request.form.get("contract_hours", 35.0))
            contract_type = request.form.get("contract_type", "CDI")
            
            # Créer l'employé
            emp = Employee(
                full_name=name, 
                position=position,
                
                # S'assurer que les IDs sont des entiers valides ou None
                team_id=int(team_id) if team_id and team_id.isdigit() else None,
                
                # NOUVEAU : Affecter directement l'établissement si fourni
                establishment_id=int(establishment_id) if establishment_id and establishment_id.isdigit() else None,
                
                contract_hours_per_week=contract_hours,
                contract_type=contract_type
            )
            
            # Logique de création de compte
            if create_account and email:
                username = name.replace(" ", ".").lower()
                new_user = User(
                    username=username, 
                    email=email, 
                    is_manager="is_manager" in request.form,
                    is_admin="is_admin" in request.form,
                    is_super_admin=False
                )
                new_user.set_password("motdepasse123") # Mot de passe temporaire
                db.session.add(new_user)
                emp.user = new_user
            
            db.session.add(emp)
            db.session.commit()
            flash(f"Employé {name} créé avec succès.", "success")
            return redirect(url_for("show_employees"))
            
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de la création de l'employé: {e}", "error")
            print(f"Erreur: {e}")
            return redirect(url_for("show_employees"))
    
    # GET: Afficher seulement les employés gérables
    employees = get_manageable_employees(current_user)
    
    # Équipes disponibles
    if current_user.is_super_admin:
        teams = Team.query.all()
    elif current_user.employee:
        managed_teams = Team.query.filter_by(manager_id=current_user.employee.id).all()
        teams = managed_teams
    else:
        teams = []
    
    # NOUVEAU : Récupérer tous les établissements
    establishments = Establishment.query.all()
    
    # Préparer les données pour le template (nom de l'équipe et de l'établissement)
    for emp in employees:
        emp.team_name = emp.team.name if emp.team else "Non assigné"
        # Utiliser la nouvelle propriété current_establishment de models.py
        emp.establishment_name = emp.current_establishment.name if emp.current_establishment else "Non assigné"

    return render_template("employees.html", employees=employees, teams=teams, establishments=establishments)

# --- CRUD Shifts ---
# ... (inchangé, car on suppose les shifts sont globaux ou seront gérés plus tard) ...

@app.route("/shifts", methods=["GET", "POST"])
@login_required
def show_shifts():
    if not current_user.is_manager and not current_user.is_super_admin:
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
        
    shifts = Shift.query.all() # Peut-être filtrer par établissement plus tard
    
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
    if not current_user.is_manager and not current_user.is_super_admin:
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
    if not current_user.is_manager and not current_user.is_super_admin:
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

# --- Gestion des Équipes (Mise à jour pour l'établissement) ---

@app.route("/teams", methods=["GET", "POST"])
@login_required
def manage_teams():
    if not current_user.is_manager and not current_user.is_super_admin:
        flash("Accès refusé", "error")
        return redirect(url_for("index"))
        
    est_id = get_current_establishment_id()
    if est_id is None and not current_user.is_super_admin:
        flash("Vous n'êtes pas lié à un établissement. Contactez un Ultra-Admin.", "error")
        return redirect(url_for("index"))
        
    if request.method == "POST":
        name = request.form["name"]
        description = request.form.get("description", "")
        
        try:
            team = Team(
                name=name,
                description=description,
                manager_id=current_user.employee.id if current_user.employee else None,
                # NOUVEAU: Liaison à l'établissement (sauf si Super Admin, auquel cas est_id est None)
                establishment_id=est_id if est_id is not None else None 
            )
            db.session.add(team)
            db.session.commit()
            flash("Équipe créée avec succès", "success")
        except Exception as e:
            db.session.rollback()
            flash("Erreur lors de la création de l'équipe", "error")
    
    # Afficher les équipes gérées/visibles
    # Ultra-Admin voit tout
    if current_user.is_super_admin:
        teams = Team.query.all()
    # Admin/Manager voit seulement dans son établissement
    elif est_id is not None:
        if current_user.is_admin:
            # Admin voit toutes les équipes de son établissement
            teams = Team.query.filter_by(establishment_id=est_id).all()
        elif current_user.employee:
            # Manager voit seulement ses équipes dans son établissement
            teams = Team.query.filter_by(manager_id=current_user.employee.id, establishment_id=est_id).all()
        else:
            teams = []
    else:
        teams = []
    
    return render_template("teams.html", teams=teams)


@app.route("/api/teams/<int:team_id>", methods=["DELETE"])
@login_required
def delete_team(team_id):
    if not current_user.is_manager and not current_user.is_super_admin:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    try:
        team = Team.query.get_or_404(team_id)
        
        # Vérifier les permissions
        # Si pas Super Admin, vérifier que l'équipe est dans le bon établissement OU qu'il est le manager
        is_admin_or_super = current_user.is_admin or current_user.is_super_admin
        
        if not is_admin_or_super:
            if team.manager_id != current_user.employee.id or team.establishment_id != get_current_establishment_id():
                 return jsonify({"success": False, "error": "Vous n'avez pas l'autorisation pour cette équipe"}), 403
        
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
    if not current_user.is_manager and not current_user.is_super_admin:
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
    if not current_user.is_manager and not current_user.is_super_admin:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    try:
        team = Team.query.get_or_404(team_id)
        
        # Vérifier les permissions de modification sur l'équipe
        is_admin_or_super = current_user.is_admin or current_user.is_super_admin
        if not is_admin_or_super:
            if team.manager_id != current_user.employee.id or team.establishment_id != get_current_establishment_id():
                 return jsonify({"success": False, "error": "Vous n'avez pas l'autorisation pour cette équipe"}), 403
        
        data = request.get_json()
        employee_ids = data.get("employee_ids", [])
        
        for emp_id in employee_ids:
            employee = Employee.query.get(emp_id)
            # Vérifier si le manager peut gérer cet employé (inclut le filtre d'établissement)
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
    if not current_user.is_manager and not current_user.is_super_admin:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    try:
        employee = Employee.query.get_or_404(employee_id)
        
        # Vérifier les permissions de modification
        if not employee.can_be_managed_by(current_user):
            return jsonify({"success": False, "error": "Vous ne pouvez pas modifier cet employé"}), 403
            
        employee.team_id = None
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": "Erreur lors de la suppression"}), 500

# --- CRUD Assignments (Fonctionne avec le nouveau get_manageable_employees) ---
@app.route("/assignments", methods=["GET", "POST"])
@login_required
def assignments():
    if not current_user.is_manager and not current_user.is_super_admin:
        flash("Accès refusé", "error")
        return redirect(url_for("employee_dashboard"))
        
    # La logique de gestion POST/GET est laissée telle quelle, car get_manageable_employees 
    # garantit que seules les assignations pertinentes sont affichées.

    if request.method == "POST":
        # ... (Logique de création d'assignation inchangée) ...
        employee_id_str = request.form.get("employee_id")
        shift_id_str = request.form.get("shift_id")
        start_str = request.form.get("start")
        end_str = request.form.get("end")
        notes = request.form.get("notes", "")

        if not all([employee_id_str, shift_id_str, start_str, end_str]):
            flash("Données manquantes pour la création de l'assignation", "error")
            return redirect(url_for("assignments"))

        try:
            employee_id = int(employee_id_str)
            shift_id = int(shift_id_str)

            # Vérifier que le manager peut assigner cet employé
            employee = Employee.query.get(employee_id)
            if not employee or not employee.can_be_managed_by(current_user):
                flash("Vous ne pouvez pas assigner cet employé", "error")
                return redirect(url_for("assignments"))

            start = datetime.fromisoformat(start_str)
            end = datetime.fromisoformat(end_str)

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
        except Exception as e:
            db.session.rollback()
            print(f"ERREUR LORS DE LA CRÉATION DE L'ASSIGNATION: {e}")
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
            
    return render_template("assignments.html", assignments=assignments, employees=manageable_employees, shifts=shifts, assignments_today=assignments_today, assignments_week=assignments_week, conflicts=conflicts)


# --- API Assignments (Mise à jour pour Super Admin) ---

@app.route("/api/assignments", methods=["POST"])
@login_required
def create_assignment():
    if not current_user.is_manager and not current_user.is_super_admin:
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
            shift_id=shift_id, # Utiliser l'entier
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
        print(f"Erreur de création d'assignation: {e}")
        return jsonify({"success": False, "error": "Erreur serveur lors de la création de l'assignation"}), 500

@app.route("/api/assignments/<int:assignment_id>", methods=["PUT"])
@login_required
def update_assignment(assignment_id):
    if not current_user.is_manager and not current_user.is_super_admin:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    try:
        assignment = Assignment.query.get_or_404(assignment_id)
        
        # Vérifier que le manager peut modifier cette assignation
        if not assignment.employee.can_be_managed_by(current_user):
            return jsonify({"success": False, "error": "Vous ne pouvez pas modifier cette assignation"}), 403
            
        employee_id_str = request.form.get("employee_id")
        shift_id_str = request.form.get("shift_id")
        start_str = request.form.get("start")
        end_str = request.form.get("end")
        notes = request.form.get("notes")

        if employee_id_str:
            employee_id = int(employee_id_str)
            # Re-vérifier la permission si l'employé est changé
            employee = Employee.query.get(employee_id)
            if not employee or not employee.can_be_managed_by(current_user):
                 return jsonify({"success": False, "error": "Nouvel employé non gérable"}), 403
            assignment.employee_id = employee_id

        if shift_id_str:
            assignment.shift_id = int(shift_id_str)

        if start_str:
            assignment.start = datetime.fromisoformat(start_str.replace("Z", "+00:00").replace(" ", "+"))
        
        if end_str:
            assignment.end = datetime.fromisoformat(end_str.replace("Z", "+00:00").replace(" ", "+"))
            
        if notes is not None:
            assignment.notes = notes

        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": "Erreur lors de la mise à jour"}), 500

@app.route("/api/assignments/<int:assignment_id>", methods=["DELETE"])
@login_required
def delete_assignment(assignment_id):
    if not current_user.is_manager and not current_user.is_super_admin:
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
    if not current_user.is_manager and not current_user.is_super_admin:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    try:
        original = Assignment.query.get_or_404(assignment_id)
        # Vérifier les permissions
        if not original.employee.can_be_managed_by(current_user):
            return jsonify({"success": False, "error": "Vous ne pouvez pas dupliquer cette assignation"}), 403
            
        duplicate = Assignment(
            employee_id=original.employee_id,
            shift_id=original.shift_id,
            start=original.start + timedelta(days=7), # Décaler d'une semaine
            end=original.end + timedelta(days=7), # Décaler d'une semaine
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
# ... (inchangé, car elles utilisent can_be_managed_by) ...
@app.route("/employees/<int:employee_id>/hours")
@login_required
def employee_hours_detail(employee_id):
    if not current_user.is_manager and not current_user.is_super_admin:
        flash("Accès refusé", "error")
        return redirect(url_for("index"))

    employee = Employee.query.get_or_404(employee_id)
    # Vérifier que le manager peut voir cet employé
    if not employee.can_be_managed_by(current_user):
        flash("Vous ne pouvez pas consulter cet employé", "error")
        return redirect(url_for("show_employees"))

    months_history = employee.get_monthly_hours_history(6)
    current_month = employee.current_month_hours_summary
    return render_template("employee_hours_detail.html", employee=employee, months_history=months_history, current_month=current_month)

@app.route("/api/employees/<int:employee_id>/contract", methods=["PUT"])
@login_required
def update_contract_hours(employee_id):
    if not current_user.is_manager and not current_user.is_super_admin:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    try:
        employee = Employee.query.get_or_404(employee_id)
        
        if not employee.can_be_managed_by(current_user):
             return jsonify({"success": False, "error": "Vous ne pouvez pas modifier cet employé"}), 403
        
        hours_per_week = float(request.form.get("hours_per_week"))
        
        if hours_per_week < 0:
            return jsonify({"success": False, "error": "Les heures ne peuvent pas être négatives"}), 400
        
        employee.update_contract_hours(hours_per_week)
        db.session.commit()
        return jsonify({"success": True, "message": "Contrat mis à jour"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": "Erreur lors de la mise à jour du contrat"}), 500

@app.route("/planning")
@login_required
def planning():
    if not current_user.is_manager and not current_user.is_super_admin:
        flash("Accès refusé", "error")
        return redirect(url_for("index"))
        
    shifts = Shift.query.all()
    # Le reste des données sera chargé par l'API JavaScript
    return render_template("planning.html", shifts=shifts)

# --- API pour les données du Gantt ---
@app.get("/api/planning-gantt")
@login_required
def api_planning_gantt():
    if not current_user.is_manager and not current_user.is_super_admin:
        return jsonify({"employees": [], "assignments": []}), 403
    
    start_str = request.args.get('start_date')
    
    if not start_str:
        start_date = datetime.now()
    else:
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
    """Récupère les statistiques pour le dashboard du planning (heures totales, conflits)."""
    
    # Si pas manager, n'affiche rien (ou erreur 403)
    if not current_user.is_manager and not current_user.is_super_admin:
        return jsonify({"error": "Accès refusé"}), 403
        
    manageable_employees = get_manageable_employees(current_user)
    manageable_ids = [emp.id for emp in manageable_employees]
    
    # Date de début de la semaine
    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    
    # Assignations de cette semaine pour les employés gérables
    week_assignments = Assignment.query.filter(
        Assignment.employee_id.in_(manageable_ids) if manageable_ids else Assignment.id == -1,
        Assignment.start >= week_start
    ).all()
    
    # Calcul des heures totales
    total_hours = sum([(a.end - a.start).total_seconds() / 3600 for a in week_assignments])
    
    # Calcul des conflits (simplifié)
    conflicts = 0
    # Logique de détection de conflit à implémenter ici (omise pour l'instant)
    
    return jsonify({
        "total_employees": len(manageable_employees),
        "total_hours_week": int(total_hours),
        "conflicts": conflicts
    })

# --- API pour les employés à surveiller (Fonctionne avec le nouveau get_manageable_employees) ---
@app.get("/api/attention-employees")
@login_required
def get_attention_employees():
    if not current_user.is_manager and not current_user.is_super_admin:
        return jsonify({"error": "Accès refusé"}), 403

    manageable_employees = get_manageable_employees(current_user)
    attention_list = []
    
    for emp in manageable_employees:
        hours_data = emp.current_month_hours_summary
        diff = abs(hours_data['difference'])
        
        # Seuil d'alerte (par exemple, plus de 10h d'écart)
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
                flash("Les nouveaux mots de passe ne correspondent pas", "error")
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
# ... (Logique d'export inchangée) ...
# (Vérifier la logique de `export_week` pour `get_gantt_data_for_week` qui est maintenant sécurisée)

# Le reste du fichier (fonctions PDF, routes d'erreurs) est inchangé et conservé.
# ---------------------------------------------------------------------------------

# --- Export CSV --- 
# ... (Logique de l'export CSV non modifiée ici, mais l'appel à get_gantt_data_for_week est sécurisé) ...

# ... (Logique pour l'export PDF non modifiée ici) ...

# ---------------------------------------------------------------------------------
@app.errorhandler(404)
def page_not_found(error):
    return """
<html>
<head><title>Erreur 404</title></head>
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

# Dans votre fichier app.py (à ajouter)

@app.route('/employees/delete/<int:employee_id>', methods=['POST'])
@login_required
@manager_required 
def delete_employee(employee_id):
    employee = Employee.query.get_or_404(employee_id)

    # Vérification de la permission
    if not current_user.is_super_admin and not employee.can_be_managed_by(current_user):
        flash('Vous n\'avez pas la permission de supprimer cet employé.', 'error')
        return redirect(url_for('show_employees'))

    try:
        # Suppression de l'utilisateur lié (si l'employé est aussi un user/manager)
        if employee.user:
            db.session.delete(employee.user)
            
        # Suppression de l'employé (entraîne la suppression en cascade des Assignments, TimesheetEntries)
        db.session.delete(employee)
        db.session.commit()
        flash(f'L\'employé {employee.full_name} a été supprimé avec succès.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur lors de la suppression de l\'employé : {e}', 'error')

    return redirect(url_for('show_employees'))

@app.route('/api/establishments/link_user', methods=['POST'])
@login_required
@manager_required
def link_user_to_establishment():
    user_id = request.form.get('user_id', type=int)
    
    # 1. Déterminer l'établissement cible (celui du manager/admin actuel)
    target_establishment_id = current_user.establishment_id
    
    if not target_establishment_id:
        # Seul un super admin sans établissement ou un admin/manager peut faire ça
        if current_user.is_super_admin:
            flash('Erreur : Sélectionnez d\'abord un établissement pour vous-même si vous voulez gérer les utilisateurs.', 'error')
            return jsonify({'success': False, 'error': 'Super Admin doit être lié.'})
        flash('Erreur : Votre compte n\'est lié à aucun établissement.', 'error')
        return jsonify({'success': False, 'error': 'Établissement non défini.'})

    user_to_link = User.query.get(user_id)
    
    if not user_to_link:
        return jsonify({'success': False, 'error': 'Utilisateur non trouvé.'})

    if user_to_link.establishment_id is not None and user_to_link.establishment_id != target_establishment_id:
        return jsonify({'success': False, 'error': 'L\'utilisateur est déjà lié à un autre établissement.'})

    try:
        # 2. Lier l'utilisateur à l'établissement du manager actuel
        user_to_link.establishment_id = target_establishment_id
        db.session.commit()
        
        # 3. Créer automatiquement un enregistrement Employee si nécessaire
        if not user_to_link.employee:
            new_employee = Employee(
                full_name=user_to_link.username,
                user_id=user_to_link.id,
                establishment_id=target_establishment_id,
                position="Employé"
            )
            db.session.add(new_employee)
            db.session.commit()
            flash(f'Compte {user_to_link.username} lié et employé créé.', 'success')
        else:
            flash(f'Compte {user_to_link.username} lié à l\'établissement.', 'success')
            
        return jsonify({'success': True, 'message': 'Utilisateur lié avec succès.'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


# MAJ : Assurez-vous d'avoir les données nécessaires dans la route /employees (GET)
# Ajoutez la requête suivante dans la route `show_employees` (GET /employees) :
# users_to_link = User.query.filter(User.establishment_id == None).all()
# et passez cette liste au template : render_template('employees.html', ..., users_to_link=users_to_link)


# --- Lancement de l'application ---

if __name__ == "__main__":
    with app.app_context():
        # Important : Après avoir modifié models.py, vous devrez peut-être recréer la DB ou faire une migration si vous utilisez Flask-Migrate.
        # Sinon, db.create_all() va créer les nouvelles tables et colonnes.
        db.create_all()
    
    # Configuration pour production Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)






