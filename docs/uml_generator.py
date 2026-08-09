from pathlib import Path

import plantuml

SOURCE = Path(__file__).parent / "architecture_as_is.puml"
OUTPUT = SOURCE.with_suffix(".png")

server = plantuml.PlantUML(url="http://www.plantuml.com/plantuml/png/")
# processes_file() читает файл через open() без encoding= — на Windows это
# берёт системную кодировку (cp1251) и падает на кириллице. Читаем сами в UTF-8.
diagram_text = SOURCE.read_text(encoding="utf-8")
OUTPUT.write_bytes(server.processes(diagram_text))