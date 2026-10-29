import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, render_template
from flask_wtf.csrf import CSRFError
from config import Config
from extensions import db, login_manager, csrf
from models import User


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("Не задан SECRET_KEY в локальном файле .env")

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    login_manager.login_view = "site.login"
    login_manager.login_message = "Сначала войдите в систему"

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (ValueError, TypeError):
            return None

    from routes import site
    app.register_blueprint(site)

    @app.errorhandler(400)
    def bad_request(error):
        return render_template("errors/error.html", code=400, message="Некорректный запрос"), 400

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return render_template("errors/error.html", code=400, message="Форма устарела. Обновите страницу и повторите действие."), 400

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/error.html", code=403, message="Недостаточно прав доступа"), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/error.html", code=404, message="Страница не найдена"), 404

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        return render_template("errors/error.html", code=500, message="Внутренняя ошибка сервера"), 500

    log_folder = Path(app.root_path) / "logs"
    log_folder.mkdir(exist_ok=True)
    audit = logging.getLogger("repair_service.admin")
    audit.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == log_folder / "admin_actions.log"
               for h in audit.handlers):
        handler = RotatingFileHandler(log_folder / "admin_actions.log",
                                      maxBytes=1_000_000, backupCount=1,
                                      encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        audit.addHandler(handler)
    audit.propagate = False
    app.extensions["admin_audit"] = audit
    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
