import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import csv
from io import StringIO

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///maihlili.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgres://"):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Import des modèles (assurez-vous que models.py contient les modèles mis à jour)
from models import User, Employee, Team, Shift, Assignment

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_manageable_employees(user):
    """Retourne les employés qu'un manager peut gérer"""
    if user.is_admin:
        return Employee.query.all()
    elif user.is_manager and user.employee:
        managed_teams = Team.query.filter_by(manager_id=user.employee.id).all()
        employee_ids = set()
        for team in managed_teams:
            employee_ids.update([e.id for e in team.members])
        return Employee.query.filter(Employee.id.in_(employee_ids)).all() if employee_ids else []
    return []

# ========== ROUTES D'AUTHENTIFICATION ==========

@app.route("/")
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    
    # Statistiques pour le dashboard
    if current_user.is_manager:
        manageable_employees = get_manageable_employees(current_user)
        total_employees = len(manageable_employees)
        
        if current_user.is_admin:
            total_teams = Team.query.count()
            total_shifts = Shift.query.count()
        else:
            total_teams = Team.query.filter_by(manager_id=current_user.employee.id).count()
            employee_ids = [e.id for e in manageable_employees]
            total_shifts = Shift.query.filter(Shift.created_by.in_(employee_ids)).count() if employee_ids else 0
        
        # Assignations du mois
        start_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_assignments = Assignment.query.filter(
            Assignment.start >= start_of_month
        ).count()
        
        return render_template("index.html",
                             total_employees=total_employees,
                             total_teams=total_teams,
                             total_shifts=total_shifts,
                             monthly_assignments=monthly_assignments)
    else:
        # Dashboard employé
        if current_user.employee:
            my_assignments = Assignment.query.filter_by(
                employee_id=current_user.employee.id
            ).filter(
                Assignment.start >= datetime.now()
            ).order_by(Assignment.start).limit(5).all()
            
            return render_template("index.html", my_assignments=my_assignments)
        
        return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash("Email ou mot de passe incorrect", "error")
    
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        
        if User.query.filter_by(email=email).first():
            flash("Cet email est déjà utilisé", "error")
            return redirect(url_for('register'))
        
        user = User(
            email=email,
            password_hash=generate_password_hash(password),
            is_manager=False,
            is_admin=False
        )
        
        db.session.add(user)
        db.session.commit()
        
        flash("Compte créé avec succès !", "success")
        return redirect(url_for('login'))
    
    return render_template("register.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old_password = request.form["old_password"]
        new_password = request.form["new_password"]
        
        if not check_password_hash(current_user.password_hash, old_password):
            flash("Ancien mot de passe incorrect", "error")
            return redirect(url_for('change_password'))
        
        current_user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        
        flash("Mot de passe modifié avec succès", "success")
        return redirect(url_for('index'))
    
    return render_template("change_password.html")

# ========== GESTION DES EMPLOYÉS (MODIFIÉ) ==========

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
        
        # NOUVEAU : Récupérer les heures contractuelles
        contract_hours = float(request.form.get("contract_hours", 35.0))
        contract_type = request.form.get("contract_type", "CDI")
        
        create_account = "create_account" in request.form
        
        try:
            # Créer l'employé avec les nouvelles informations
            emp = Employee(
                full_name=name,
                position=position,
                team_id=int(team_id) if team_id else None,
                contract_hours_per_week=contract_hours,
                contract_type=contract_type
            )
            
            # Mettre à jour automatiquement les heures mensuelles
            emp.update_contract_hours(contract_hours)
            
            # Créer le compte utilisateur si demandé
            if create_account and email:
                if User.query.filter_by(email=email).first():
                    flash("Un compte avec cet email existe déjà", "error")
                    return redirect(url_for("show_employees"))
                
                user = User(
                    email=email,
                    password_hash=generate_password_hash("password123"),
                    is_manager=False,
                    is_admin=False
                )
                db.session.add(user)
                db.session.flush()
                emp.user_id = user.id
            
            db.session.add(emp)
            db.session.commit()
            
            flash(f"Employé {name} créé avec succès", "success")
            return redirect(url_for("show_employees"))
        
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de la création: {str(e)}", "error")
            return redirect(url_for("show_employees"))
    
    # GET: Afficher les employés
    employees = get_manageable_employees(current_user)
    
    # NOUVEAU : Ajouter les données d'heures pour chaque employé
    for e in employees:
        e.avatar = 'USER'
        e.role = e.position or 'Employé'
        e.status = 'active' if e.is_active else 'absent'
        # Ajouter les statistiques d'heures
        e.hours_summary = e.current_month_hours_summary
    
    # Équipes disponibles
    teams = []
    if current_user.is_admin:
        teams = Team.query.all()
    elif current_user.employee:
        teams = Team.query.filter_by(manager_id=current_user.employee.id).all()
    
    return render_template("employees.html", employees=employees, teams=teams)

# NOUVELLE ROUTE : Détails des heures d'un employé
@app.route("/employees/<int:employee_id>/hours")
@login_required
def employee_hours_detail(employee_id):
    if not current_user.is_manager:
        flash("Accès refusé", "error")
        return redirect(url_for("index"))
    
    employee = Employee.query.get_or_404(employee_id)
    
    # Vérifier que le manager peut voir cet employé
    manageable_employees = get_manageable_employees(current_user)
    if employee not in manageable_employees:
        flash("Vous ne pouvez pas consulter cet employé", "error")
        return redirect(url_for("show_employees"))
    
    # Récupérer l'historique des heures
    months_history = employee.get_monthly_hours_history(6)
    current_month = employee.current_month_hours_summary
    
    return render_template("employee_hours_detail.html",
                         employee=employee,
                         months_history=months_history,
                         current_month=current_month)

# ========== API EMPLOYÉS (MODIFIÉ) ==========

@app.route("/api/employees/<int:employee_id>", methods=["PUT"])
@login_required
def update_employee(employee_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    employee = Employee.query.get_or_404(employee_id)
    
    manageable_employees = get_manageable_employees(current_user)
    if employee not in manageable_employees:
        return jsonify({"success": False, "error": "Non autorisé"}), 403
    
    try:
        if request.form:
            employee.full_name = request.form.get("full_name", employee.full_name)
            employee.position = request.form.get("position", employee.position)
        
        db.session.commit()
        return jsonify({"success": True})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/employees/<int:employee_id>", methods=["DELETE"])
@login_required
def delete_employee(employee_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    employee = Employee.query.get_or_404(employee_id)
    
    manageable_employees = get_manageable_employees(current_user)
    if employee not in manageable_employees:
        return jsonify({"success": False, "error": "Non autorisé"}), 403
    
    try:
        db.session.delete(employee)
        db.session.commit()
        return jsonify({"success": True})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# NOUVELLE API : Mettre à jour les heures contractuelles
@app.route("/api/employees/<int:employee_id>/contract", methods=["PUT"])
@login_required
def update_employee_contract(employee_id):
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    employee = Employee.query.get_or_404(employee_id)
    
    manageable_employees = get_manageable_employees(current_user)
    if employee not in manageable_employees:
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

# NOUVELLE API : Statistiques d'heures pour le dashboard
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

# NOUVELLE API : Employés nécessitant une attention
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
        
        # Si différence > 10h, nécessite attention
        if diff > 10:
            attention_list.append({
                "id": emp.id,
                "name": emp.full_name,
                "position": emp.position,
                "difference": hours_data['difference'],
                "status": hours_data['status']
            })
    
    # Trier par différence absolue décroissante
    attention_list.sort(key=lambda x: abs(x['difference']), reverse=True)
    
    return jsonify(attention_list)

# ========== GESTION DES ÉQUIPES ==========

@app.route("/teams", methods=["GET", "POST"])
@login_required
def show_teams():
    if not current_user.is_manager:
        flash("Accès refusé", "error")
        return redirect(url_for("index"))
    
    if request.method == "POST":
        name = request.form["name"]
        description = request.form.get("description", "")
        manager_id = request.form.get("manager_id")
        
        team = Team(
            name=name,
            description=description,
            manager_id=int(manager_id) if manager_id else None
        )
        
        db.session.add(team)
        db.session.commit()
        
        flash(f"Équipe {name} créée", "success")
        return redirect(url_for("show_teams"))
    
    if current_user.is_admin:
        teams = Team.query.all()
        all_employees = Employee.query.all()
    else:
        teams = Team.query.filter_by(manager_id=current_user.employee.id).all()
        all_employees = get_manageable_employees(current_user)
    
    return render_template("teams.html", teams=teams, all_employees=all_employees)

@app.route("/api/teams/<int:team_id>", methods=["DELETE"])
@login_required
def delete_team(team_id):
    if not current_user.is_manager:
        return jsonify({"success": False}), 403
    
    team = Team.query.get_or_404(team_id)
    
    if not current_user.is_admin and team.manager_id != current_user.employee.id:
        return jsonify({"success": False}), 403
    
    db.session.delete(team)
    db.session.commit()
    
    return jsonify({"success": True})

# ========== GESTION DES SHIFTS ==========

@app.route("/shifts", methods=["GET", "POST"])
@login_required
def show_shifts():
    if not current_user.is_manager:
        flash("Accès refusé", "error")
        return redirect(url_for("index"))
    
    if request.method == "POST":
        name = request.form["name"]
        start_time = request.form["start_time"]
        end_time = request.form["end_time"]
        color = request.form.get("color", "#3B82F6")
        
        shift = Shift(
            name=name,
            start_time=datetime.strptime(start_time, "%H:%M").time(),
            end_time=datetime.strptime(end_time, "%H:%M").time(),
            color=color,
            created_by=current_user.employee.id if current_user.employee else None
        )
        
        db.session.add(shift)
        db.session.commit()
        
        flash(f"Service {name} créé", "success")
        return redirect(url_for("show_shifts"))
    
    shifts = Shift.query.all()
    return render_template("shifts.html", shifts=shifts)

@app.route("/api/shifts/<int:shift_id>", methods=["DELETE"])
@login_required
def delete_shift(shift_id):
    if not current_user.is_manager:
        return jsonify({"success": False}), 403
    
    shift = Shift.query.get_or_404(shift_id)
    db.session.delete(shift)
    db.session.commit()
    
    return jsonify({"success": True})

# ========== GESTION DU PLANNING ==========

@app.route("/planning")
@login_required
def show_planning():
    if current_user.is_manager:
        employees = get_manageable_employees(current_user)
        shifts = Shift.query.all()
        teams = Team.query.all() if current_user.is_admin else Team.query.filter_by(manager_id=current_user.employee.id).all()
        return render_template("planning.html", employees=employees, shifts=shifts, teams=teams)
    else:
        return render_template("planning.html", employees=[], shifts=[], teams=[])

@app.route("/api/assignments")
@login_required
def get_assignments():
    start = request.args.get('start')
    end = request.args.get('end')
    
    query = Assignment.query
    
    if start:
        query = query.filter(Assignment.start >= datetime.fromisoformat(start.replace('Z', '+00:00')))
    if end:
        query = query.filter(Assignment.end <= datetime.fromisoformat(end.replace('Z', '+00:00')))
    
    if not current_user.is_manager:
        if current_user.employee:
            query = query.filter_by(employee_id=current_user.employee.id)
        else:
            return jsonify([])
    
    assignments = query.all()
    
    return jsonify([{
        'id': a.id,
        'title': f"{a.employee.full_name} - {a.shift.name}" if a.employee and a.shift else "Assignation",
        'start': a.start.isoformat(),
        'end': a.end.isoformat(),
        'backgroundColor': a.shift.color if a.shift else '#3B82F6',
        'borderColor': a.shift.color if a.shift else '#3B82F6',
        'extendedProps': {
            'employeeId': a.employee_id,
            'employeeName': a.employee.full_name if a.employee else "",
            'shiftId': a.shift_id,
            'shiftName': a.shift.name if a.shift else "",
            'status': a.status,
            'notes': a.notes or ""
        }
    } for a in assignments])

@app.route("/api/assignments", methods=["POST"])
@login_required
def create_assignment():
    if not current_user.is_manager:
        return jsonify({"success": False, "error": "Accès refusé"}), 403
    
    data = request.get_json()
    
    assignment = Assignment(
        employee_id=data['employee_id'],
        shift_id=data['shift_id'],
        start=datetime.fromisoformat(data['start'].replace('Z', '+00:00')),
        end=datetime.fromisoformat(data['end'].replace('Z', '+00:00')),
        status='scheduled',
        notes=data.get('notes', '')
    )
    
    db.session.add(assignment)
    db.session.commit()
    
    return jsonify({"success": True, "id": assignment.id})

@app.route("/api/assignments/<int:assignment_id>", methods=["PUT"])
@login_required
def update_assignment(assignment_id):
    if not current_user.is_manager:
        return jsonify({"success": False}), 403
    
    assignment = Assignment.query.get_or_404(assignment_id)
    data = request.get_json()
    
    if 'start' in data:
        assignment.start = datetime.fromisoformat(data['start'].replace('Z', '+00:00'))
    if 'end' in data:
        assignment.end = datetime.fromisoformat(data['end'].replace('Z', '+00:00'))
    if 'employee_id' in data:
        assignment.employee_id = data['employee_id']
    if 'shift_id' in data:
        assignment.shift_id = data['shift_id']
    if 'status' in data:
        assignment.status = data['status']
    if 'notes' in data:
        assignment.notes = data['notes']
    
    db.session.commit()
    
    return jsonify({"success": True})

@app.route("/api/assignments/<int:assignment_id>", methods=["DELETE"])
@login_required
def delete_assignment(assignment_id):
    if not current_user.is_manager:
        return jsonify({"success": False}), 403
    
    assignment = Assignment.query.get_or_404(assignment_id)
    db.session.delete(assignment)
    db.session.commit()
    
    return jsonify({"success": True})

# ========== EXPORT CSV ==========

@app.route("/export-csv")
@login_required
def export_csv():
    if not current_user.is_manager:
        flash("Accès refusé", "error")
        return redirect(url_for("index"))
    
    start_date = request.args.get('start')
    end_date = request.args.get('end')
    
    query = Assignment.query
    if start_date:
        query = query.filter(Assignment.start >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.filter(Assignment.end <= datetime.fromisoformat(end_date))
    
    assignments = query.all()
    
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Employé', 'Service', 'Début', 'Fin', 'Statut', 'Notes'])
    
    for a in assignments:
        writer.writerow([
            a.employee.full_name if a.employee else "",
            a.shift.name if a.shift else "",
            a.start.strftime("%Y-%m-%d %H:%M"),
            a.end.strftime("%Y-%m-%d %H:%M"),
            a.status,
            a.notes or ""
        ])
    
    output.seek(0)
    return output.getvalue(), 200, {
        'Content-Type': 'text/csv',
        'Content-Disposition': 'attachment; filename=planning_export.csv'
    }

# ========== INITIALISATION ==========

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
