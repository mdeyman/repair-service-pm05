from functools import wraps

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import RepairRequest, Status, User
from . import site


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def audit(action, record_id):
    current_app.extensions["admin_audit"].info(
        "admin_id=%s action=%s request_id=%s", current_user.id, action, record_id
    )


def valid_request_data(form):
    device = form.get("device_type", "").strip()
    problem = form.get("problem_description", "").strip()
    contact = form.get("contact_method", "").strip()
    if not (1 <= len(device) <= 100 and 1 <= len(problem) <= 2000 and contact in ("Телефон", "Email")):
        return None
    return device, problem, contact


def form_entities(form):
    user_id = form.get("user_id", type=int)
    status_id = form.get("status_id", type=int)
    user = db.session.get(User, user_id) if user_id else None
    status = db.session.get(Status, status_id) if status_id else None
    return user, status


@site.route("/")
def index():
    return redirect(url_for("site.login"))


@site.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("site.admin" if current_user.role == "admin" else "site.dashboard"))
    if request.method == "POST":
        login = request.form.get("login", "").strip()
        password = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        if not (3 <= len(login) <= 50 and len(password) >= 8 and
                1 <= len(full_name) <= 100 and 1 <= len(phone) <= 20 and
                3 <= len(email) <= 100 and "@" in email):
            flash("Проверьте правильность и длину заполненных полей")
            return render_template("register.html"), 400
        user = User(login=login, password_hash=generate_password_hash(password),
                    full_name=full_name, phone=phone, email=email, role="user")
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Пользователь с таким логином уже существует")
            return render_template("register.html"), 400
        flash("Регистрация выполнена успешно")
        return redirect(url_for("site.login"))
    return render_template("register.html")


@site.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("site.admin" if current_user.role == "admin" else "site.dashboard"))
    if request.method == "POST":
        login_value = request.form.get("login", "").strip()
        password = request.form.get("password", "")
        user = db.session.scalar(select(User).where(User.login == login_value))
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("site.admin" if user.role == "admin" else "site.dashboard"))
        flash("Неверный логин или пароль")
    return render_template("login.html")


@site.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("site.login"))


@site.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    if current_user.role == "admin":
        return redirect(url_for("site.admin"))
    if request.method == "POST":
        data = valid_request_data(request.form)
        if not data:
            flash("Проверьте поля заявки")
            return redirect(url_for("site.dashboard"))
        status = db.session.scalar(select(Status).where(Status.name == "Новая"))
        if not status:
            abort(500)
        row = RepairRequest(user_id=current_user.id, status_id=status.id,
                            device_type=data[0], problem_description=data[1],
                            contact_method=data[2])
        db.session.add(row)
        db.session.commit()
        flash("Заявка создана")
        return redirect(url_for("site.dashboard"))
    requests_list = db.session.scalars(
        select(RepairRequest).where(RepairRequest.user_id == current_user.id)
        .order_by(RepairRequest.id.desc())
    ).all()
    return render_template("dashboard.html", requests_list=requests_list)


@site.route("/admin")
@admin_required
def admin():
    text = request.args.get("q", "").strip()[:100]
    status_filter = request.args.get("status", type=int)
    page = max(1, request.args.get("page", default=1, type=int))
    query = select(RepairRequest).join(RepairRequest.user)
    if text:
        term = f"%{text}%"
        query = query.where(or_(RepairRequest.device_type.ilike(term),
                                RepairRequest.problem_description.ilike(term),
                                User.full_name.ilike(term)))
    if status_filter:
        query = query.where(RepairRequest.status_id == status_filter)
    pagination = db.paginate(query.order_by(RepairRequest.id.desc()),
                             page=page, per_page=5, error_out=False)
    statuses = db.session.scalars(select(Status).order_by(Status.id)).all()
    return render_template("admin.html", all_requests=pagination.items,
                           statuses=statuses, pagination=pagination,
                           q=text, selected_status=status_filter)


@site.route("/admin/requests/new", methods=["GET", "POST"])
@admin_required
def request_new():
    if request.method == "POST":
        data = valid_request_data(request.form)
        user, status = form_entities(request.form)
        if not data or not user or not status:
            flash("Заполните все поля корректно")
        else:
            row = RepairRequest(user_id=user.id, status_id=status.id,
                                device_type=data[0], problem_description=data[1],
                                contact_method=data[2])
            db.session.add(row)
            db.session.commit()
            audit("create", row.id)
            flash("Заявка добавлена")
            return redirect(url_for("site.admin"))
    return render_template("request_form.html", item=None,
                           users=db.session.scalars(select(User).order_by(User.id)).all(),
                           statuses=db.session.scalars(select(Status).order_by(Status.id)).all())


@site.route("/admin/requests/<int:request_id>/edit", methods=["GET", "POST"])
@admin_required
def request_edit(request_id):
    row = db.get_or_404(RepairRequest, request_id)
    if request.method == "POST":
        data = valid_request_data(request.form)
        user, status = form_entities(request.form)
        if not data or not user or not status:
            flash("Заполните все поля корректно")
        else:
            row.user_id = user.id
            row.status_id = status.id
            row.device_type, row.problem_description, row.contact_method = data
            db.session.commit()
            audit("edit", row.id)
            flash("Заявка изменена")
            return redirect(url_for("site.admin"))
    return render_template("request_form.html", item=row,
                           users=db.session.scalars(select(User).order_by(User.id)).all(),
                           statuses=db.session.scalars(select(Status).order_by(Status.id)).all())


@site.route("/admin/requests/<int:request_id>/status", methods=["POST"])
@admin_required
def request_status(request_id):
    row = db.get_or_404(RepairRequest, request_id)
    status_id = request.form.get("status_id", type=int)
    status = db.session.get(Status, status_id) if status_id else None
    if status is None:
        abort(400)
    row.status_id = status.id
    db.session.commit()
    audit("status", row.id)
    flash("Статус изменён")
    return redirect(url_for("site.admin"))


@site.route("/admin/requests/<int:request_id>/delete", methods=["POST"])
@admin_required
def request_delete(request_id):
    row = db.get_or_404(RepairRequest, request_id)
    db.session.delete(row)
    db.session.commit()
    audit("delete", request_id)
    flash("Заявка удалена")
    return redirect(url_for("site.admin"))
