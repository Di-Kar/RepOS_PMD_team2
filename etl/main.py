
import logging
import sys
from app.config import AppConfig
from app.etl import ETLPipeline

def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    try:
        config = AppConfig()
        logger.info("Конфигурация успешно загружена.")
        pipeline = ETLPipeline(config)
        pipeline.run()
    except Exception as e:
        logger.error(f"Не удалось запустить сервис: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()