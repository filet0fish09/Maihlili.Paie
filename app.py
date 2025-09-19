from flask import Flask, render_template, request, redirect, url_for, jsonify
from models import db, User, Employee, Shift, Assignment, Team
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///maihlili_spv.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "maihlili_secret_key_2024")
db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_manageable_employees(user):
    """Retourne les employÃ©s qu'un manager peut gÃ©rer"""
    if user.is_admin:
        return Employee.query.filter_by(is_active=True).all()
    
    if not user.is_manager:
        return []
    
    manager_employee = user.employee
    if not manager_employee:
        return []
    
    # EmployÃ©s des Ã©quipes gÃ©rÃ©es par ce manager
    managed_teams = Team.query.filter_by(manager_id=manager_employee.id).all()
    team_employees = []
    for team in managed_teams:
        team_employees.extend(team.members)
    
    # EmployÃ©s sans Ã©quipe (si le manager peut les gÃ©rer)
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
        
        # GÃ©rer les rÃ´les
        role = request.form.get("role", "employee")
        is_manager = (role in ["manager", "admin"])
        is_admin = (role == "admin")

        if User.query.filter_by(email=email).first():
            return "Email dÃ©jÃ  utilisÃ©", 400

        # CrÃ©er l'utilisateur
        user = User(username=username, email=email, is_manager=is_manager, is_admin=is_admin)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        # CrÃ©er automatiquement l'employÃ© associÃ©
        emp = Employee(full_name=username, user=user)
        db.session.add(emp)
        db.session.commit()
        
        return redirect(url_for("login"))

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
            login_user(user)
            
            # Rediriger selon le rÃ´le
            if user.is_manager:
                return redirect(url_for("index"))  # Dashboard manager
            else:
                return redirect(url_for("employee_dashboard"))  # Dashboard employÃ©
        
        return "Nom d'utilisateur/email ou mot de passe incorrect", 400
    
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

# --- Dashboard Principal ---

@app.route("/")
@login_required
def index():
    if not current_user.is_manager:
        return redirect(url_for("employee_dashboard"))
    
    # Statistiques basÃ©es sur les employÃ©s gÃ©rables
    manageable_employees = get_manageable_employees(current_user)
    manageable_ids = [emp.id for emp in manageable_employees]
    
    total_employees = len(manageable_employees)
    total_shifts_today = Shift.query.count()
    
    # Assignations de cette semaine pour les employÃ©s gÃ©rables
    week_start = datetime.now() - timedelta(days=datetime.now().weekday())
    week_assignments = Assignment.query.filter(
        Assignment.employee_id.in_(manageable_ids) if manageable_ids else Assignment.id == -1,
        Assignment.start >= week_start
    ).all()
    
    total_hours = sum([(a.end - a.start).total_seconds() / 3600 for a in week_assignments])
    conflicts = 0
    
    return render_template("index.html", 
                         total_employees=total_employees,
                         total_shifts_today=len(week_assignments),
                         total_hours=int(total_hours),
                         conflicts=conflicts,
                         manageable_employees=manageable_employees)

# --- Dashboard EmployÃ© ---

@app.route("/employee-dashboard")
@login_required
def employee_dashboard():
    if current_user.is_manager:
        return redirect(url_for("index"))
    
    # RÃ©cupÃ©rer seulement les assignations de cet employÃ©
    employee = current_user.employee
    if not employee:
        return "Profil employÃ© non trouvÃ©", 404
    
    my_assignments = Assignment.query.filter_by(employee_id=employee.id).order_by(Assignment.start.desc()).all()
    
    # Statistiques de l'employÃ©
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

# --- API Ã‰vÃ©nements ---

@app.get("/api/events")
@login_required
def api_events():
    start_str = request.args.get("start")
    end_str = request.args.get("end")
    
    if current_user.is_manager:
        # Manager : voir les assignations de ses employÃ©s
        manageable_employees = get_manageable_employees(current_user)
        manageable_ids = [emp.id for emp in manageable_employees]
        if manageable_ids:
            q = Assignment.query.filter(Assignment.employee_id.in_(manageable_ids))
        else:
            return jsonify([])
    else:
        # EmployÃ© : voir seulement ses assignations
        emp = current_user.employee
        if not emp:
            return jsonify([])
        q = Assignment.query.filter(Assignment.employee_id == emp.id)

    if start_str:
        q = q.filter(Assignment.end >= datetime.fromisoformat(start_str.replace("Z", "+00:00")))
    if end_str:
        q = q.filter(Assignment.start <= datetime.fromisoformat(end_str.replace("Z", "+00:00")))

    events = [a.as_fullcalendar() for a in q.all()]
    return jsonify(events)

# --- CRUD EmployÃ©s ---

@app.route("/employees", methods=["GET", "POST"])
@login_required
def show_employees():
    if not current_user.is_manager:
        return "AccÃ¨s refusÃ©", 403
        
    if request.method == "POST":
        name = request.form["full_name"]
        position = request.form.get("position")
        email = request.form.get("email")
        team_id = request.form.get("team_id")
        
        # CrÃ©er l'employÃ©
        emp = Employee(
            full_name=name, 
            position=position,
            team_id=int(team_id) if team_id else None
        )
        
        # CrÃ©er un compte utilisateur si email fourni
        if email:
            if not User.query.filter_by(email=email).first():
                user = User(
                    username=name.lower().replace(' ', ''),
                    email=email,
                    is_manager=False
                )
                user.set_password("motdepasse123")  # Mot de passe par dÃ©faut
                db.session.add(user)
                db.session.flush()  # Pour obtenir l'ID
                emp.user_id = user.id
        
        db.session.add(emp)
        db.session.commit()
        
    # Afficher seulement les employÃ©s gÃ©rables
    employees = get_manageable_employees(current_user)
    
    # Ajouter des attributs pour l'affichage
    for e in employees:
        e.avatar = 'ðŸ‘¤'
        e.role = e.position or 'EmployÃ©'
        e.status = 'active' if e.is_active else 'absent'
        
    # Ã‰quipes disponibles pour ce manager
    teams = []
    if current_user.is_admin:
        teams = Team.query.all()
    elif current_user.employee:
        teams = Team.query.filter_by(manager_id=current_user.employee.id).all()
    
    return render_template("employees.html", employees=employees, teams=teams)

@app.route("/api/employees/<int:employee_id>", methods=["PUT"])
@login_required
def update_employee(employee_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "AccÃ¨s refusÃ©"}), 403
    
    employee = Employee.query.get_or_404(employee_id)
    
    # VÃ©rifier que le manager peut modifier cet employÃ©
    if not employee.can_be_managed_by(current_user):
        return jsonify({"success": False, "error": "Vous ne pouvez pas modifier cet employÃ©"}), 403
    
    employee.full_name = request.form.get("full_name", employee.full_name)
    employee.position = request.form.get("position", employee.position)
    
    db.session.commit()
    return jsonify({"success": True})

@app.route("/api/employees/<int:employee_id>", methods=["DELETE"])
@login_required
def delete_employee(employee_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "AccÃ¨s refusÃ©"}), 403
    
    employee = Employee.query.get_or_404(employee_id)
    
    # VÃ©rifier que le manager peut supprimer cet employÃ©
    if not employee.can_be_managed_by(current_user):
        return jsonify({"success": False, "error": "Vous ne pouvez pas supprimer cet employÃ©"}), 403
    
    # DÃ©sactiver plutÃ´t que supprimer
    employee.is_active = False
    db.session.commit()
    
    return jsonify({"success": True})

# --- CRUD Shifts ---

@app.route("/shifts", methods=["GET", "POST"])
@login_required
def show_shifts():
    if not current_user.is_manager:
        return "AccÃ¨s refusÃ©", 403
        
    if request.method == "POST":
        name = request.form["name"]
        color = request.form.get("color", "#3788d8")
        start_time = request.form.get("start_time", "08:00")
        end_time = request.form.get("end_time", "16:00")
        
        shift = Shift(
            name=name, 
            color=color,
            start_time=start_time,
            end_time=end_time
        )
        db.session.add(shift)
        db.session.commit()
        
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
        return jsonify({"success": False, "error": "AccÃ¨s refusÃ©"}), 403
    
    shift = Shift.query.get_or_404(shift_id)
    db.session.delete(shift)
    db.session.commit()
    
    return jsonify({"success": True})

# --- Gestion des Ã‰quipes ---

@app.route("/teams", methods=["GET", "POST"])
@login_required
def manage_teams():
    if not current_user.is_manager:
        return "AccÃ¨s refusÃ©", 403
        
    if request.method == "POST":
        name = request.form["name"]
        description = request.form.get("description", "")
        
        team = Team(
            name=name,
            description=description,
            manager_id=current_user.employee.id if current_user.employee else None
        )
        db.session.add(team)
        db.session.commit()
    
    # Afficher les Ã©quipes gÃ©rÃ©es
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
        return jsonify({"success": False, "error": "AccÃ¨s refusÃ©"}), 403
    
    team = Team.query.get_or_404(team_id)
    
    # VÃ©rifier les permissions
    if not current_user.is_admin and team.manager_id != current_user.employee.id:
        return jsonify({"success": False, "error": "Vous ne pouvez pas supprimer cette Ã©quipe"}), 403
    
    # Retirer les employÃ©s de l'Ã©quipe avant de la supprimer
    for member in team.members:
        member.team_id = None
    
    db.session.delete(team)
    db.session.commit()
    
    return jsonify({"success": True})

@app.route("/api/unassigned-employees")
@login_required
def get_unassigned_employees():
    if not current_user.is_manager:
        return jsonify([])
    
    # EmployÃ©s sans Ã©quipe que le manager peut gÃ©rer
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
        return jsonify({"success": False, "error": "AccÃ¨s refusÃ©"}), 403
    
    team = Team.query.get_or_404(team_id)
    
    # VÃ©rifier les permissions
    if not current_user.is_admin and team.manager_id != current_user.employee.id:
        return jsonify({"success": False, "error": "Vous ne pouvez pas modifier cette Ã©quipe"}), 403
    
    data = request.get_json()
    employee_ids = data.get("employee_ids", [])
    
    for emp_id in employee_ids:
        employee = Employee.query.get(emp_id)
        if employee and employee.can_be_managed_by(current_user):
            employee.team_id = team_id
    
    db.session.commit()
    return jsonify({"success": True})

@app.route("/api/teams/<int:team_id>/remove/<int:employee_id>", methods=["POST"])
@login_required
def remove_employee_from_team(team_id, employee_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "AccÃ¨s refusÃ©"}), 403
    
    employee = Employee.query.get_or_404(employee_id)
    
    if not employee.can_be_managed_by(current_user):
        return jsonify({"success": False, "error": "Vous ne pouvez pas modifier cet employÃ©"}), 403
    
    employee.team_id = None
    db.session.commit()
    
    return jsonify({"success": True})

# --- Assignations ---

@app.route("/assignments", methods=["GET", "POST"])
@login_required
def assignments():
    if not current_user.is_manager:
        return "AccÃ¨s refusÃ©", 403
        
    if request.method == "POST":
        employee_id = request.form["employee_id"]
        shift_id = request.form["shift_id"]
        start_date = request.form["start_date"]
        start_time = request.form["start_time"]
        end_date = request.form["end_date"]
        end_time = request.form["end_time"]
        notes = request.form.get("notes", "")
        
        # VÃ©rifier que le manager peut assigner cet employÃ©
        employee = Employee.query.get(employee_id)
        if not employee or not employee.can_be_managed_by(current_user):
            return "Vous ne pouvez pas assigner cet employÃ©", 403
        
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
        
        return redirect(url_for("assignments"))
    
    # Afficher seulement les assignations des employÃ©s gÃ©rables
    manageable_employees = get_manageable_employees(current_user)
    manageable_ids = [emp.id for emp in manageable_employees]
    
    if manageable_ids:
        assignments = Assignment.query.filter(
            Assignment.employee_id.in_(manageable_ids)
        ).order_by(Assignment.start.desc()).all()
    else:
        assignments = []
    
    shifts = Shift.query.all()
    
    return render_template("assignments.html", 
                         assignments=assignments,
                         employees=manageable_employees, 
                         shifts=shifts)

@app.route("/api/assignments", methods=["POST"])
@login_required
def create_assignment():
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "AccÃ¨s refusÃ©"}), 403
    
    try:
        employee_id = request.form.get("employee_id")
        shift_id = request.form.get("shift_id") 
        start_str = request.form.get("start")
        end_str = request.form.get("end")
        
        if not all([employee_id, shift_id, start_str, end_str]):
            return jsonify({"success": False, "error": "DonnÃ©es manquantes"}), 400
        
        # VÃ©rifier que le manager peut assigner cet employÃ©
        employee = Employee.query.get(employee_id)
        if not employee or not employee.can_be_managed_by(current_user):
            return jsonify({"success": False, "error": "Vous ne pouvez pas assigner cet employÃ©"}), 403
        
        start = datetime.fromisoformat(start_str.replace('T', ' '))
        end = datetime.fromisoformat(end_str.replace('T', ' '))
        
        assignment = Assignment(
            employee_id=int(employee_id),
            shift_id=int(shift_id),
            start=start,
            end=end,
            created_by=current_user.id
        )
        
        db.session.add(assignment)
        db.session.commit()
        
        return jsonify({"success": True})
        
    except Exception as e:
        print(f"Erreur: {str(e)}")
        return jsonify({"success": False, "error": "Erreur lors de la crÃ©ation"}), 500

@app.route("/api/assignments/<int:assignment_id>", methods=["DELETE"])
@login_required
def delete_assignment(assignment_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "AccÃ¨s refusÃ©"}), 403
    
    assignment = Assignment.query.get_or_404(assignment_id)
    
    # VÃ©rifier que le manager peut supprimer cette assignation
    if not assignment.employee.can_be_managed_by(current_user):
        return jsonify({"success": False, "error": "Vous ne pouvez pas supprimer cette assignation"}), 403
    
    db.session.delete(assignment)
    db.session.commit()
    
    return jsonify({"success": True})

@app.route("/api/assignments/<int:assignment_id>/duplicate", methods=["POST"])
@login_required
def duplicate_assignment(assignment_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "AccÃ¨s refusÃ©"}), 403
    
    original = Assignment.query.get_or_404(assignment_id)
    
    # VÃ©rifier les permissions
    if not original.employee.can_be_managed_by(current_user):
        return jsonify({"success": False, "error": "Vous ne pouvez pas dupliquer cette assignation"}), 403
    
    # CrÃ©er une nouvelle assignation basÃ©e sur l'originale
    duplicate = Assignment(
        employee_id=original.employee_id,
        shift_id=original.shift_id,
        start=original.start + timedelta(days=7),  # DÃ©caler d'une semaine
        end=original.end + timedelta(days=7),
        notes=original.notes,
        created_by=current_user.id
    )
    
    db.session.add(duplicate)
    db.session.commit()
    
    return jsonify({"success": True})

# --- ParamÃ¨tres ---

@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html")

@app.route("/api/change-password", methods=["POST"])
@login_required
def change_password():
    current_password = request.form["current_password"]
    new_password = request.form["new_password"]
    confirm_password = request.form["confirm_password"]
    
    # VÃ©rifier le mot de passe actuel
    if not current_user.check_password(current_password):
        return jsonify({"success": False, "error": "Mot de passe actuel incorrect"}), 400
    
    # VÃ©rifier que les nouveaux mots de passe correspondent
    if new_password != confirm_password:
        return jsonify({"success": False, "error": "Les mots de passe ne correspondent pas"}), 400
    
    # Changer le mot de passe
    current_user.set_password(new_password)
    db.session.commit()
    
    return jsonify({"success": True, "message": "Mot de passe changÃ© avec succÃ¨s"})

# --- Export CSV ---

@app.route("/export/week")
@login_required
def export_week():
    if not current_user.is_manager:
        return "AccÃ¨s refusÃ©", 403
        
    import csv
    from io import StringIO
    
    # Exporter seulement les assignations des employÃ©s gÃ©rables
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

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)