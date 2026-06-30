"""启动前配置校验。

用于 CI/CD 或部署前检查：
python -m scripts.check_config
"""

from __future__ import annotations


def main() -> None:
    try:
        from app.core.config import settings
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"config_invalid: {exc}") from None
    print(f"config_ok env={settings.APP_ENV.value} project={settings.PROJECT_NAME} version={settings.VERSION}")


if __name__ == "__main__":
    main()
