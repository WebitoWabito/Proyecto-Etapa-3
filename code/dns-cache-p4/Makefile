P4_SRC    = router.p4
P4_INFO   = router.p4info.txtpb
BUILD_DIR = build

PYTHON ?= python3

.PHONY: all compile run control test clean help

all: compile

compile:
	@echo "Compilando $(P4_SRC)"
	@mkdir -p $(BUILD_DIR)
	p4c --target bmv2 --arch v1model \
	    --p4runtime-files $(P4_INFO) \
	    -o $(BUILD_DIR) \
	    $(P4_SRC)
	@echo "Compilación exitosa"
	@ls -lh $(BUILD_DIR)/

run: compile
	@echo "Iniciando topología Mininet"
	sudo -E env "PATH=$$PATH" "PYTHONPATH=$$PYTHONPATH" $(PYTHON) topology.py

control:
	@echo "Instalando reglas LPM"
	$(PYTHON) controller.py

test: compile
	@echo "Ejecutando pruebas automáticas"
	sudo -E env "PATH=$$PATH" "PYTHONPATH=$$PYTHONPATH" $(PYTHON) topology.py --auto-test

clean:
	@echo "Limpiando artefactos"
	rm -rf $(BUILD_DIR) router.p4info.txt router.p4info.txtpb
	sudo rm -rf /tmp/lab1-router-logs
	@echo "Listo"

help:
	@echo "make        -> compilar router.p4"
	@echo "make run    -> levantar Mininet"
	@echo "make control -> cargar reglas LPM"
	@echo "make test   -> ejecutar pruebas automáticas"
	@echo "make clean  -> limpiar archivos generados"
