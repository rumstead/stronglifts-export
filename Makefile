SHELL := /bin/bash

CONTAINER_RUNTIME ?= docker
IMAGE_REPO ?= ghcr.io/rumstead/lifting-data
TAG ?= $(shell date +%Y%m%d-%H%M%S)
IMAGE ?= $(IMAGE_REPO):$(TAG)
SMOKE_DIR ?= /tmp/lifting-data-smoke
SMOKE_CSV ?= $(SMOKE_DIR)/strong-smoke.csv
SMOKE_DB ?= $(SMOKE_DIR)/lifts-smoke.db
SMOKE_HTML ?= $(SMOKE_DIR)/bench-smoke.html
SMOKE_EXERCISE ?= Bench Press
SMOKE_MOUNT ?= /smoke

.PHONY: help image-build image-publish image-smoke print-image

help:
	@echo "Targets:"
	@echo "  make image-build      Build $(IMAGE)"
	@echo "  make image-publish    Build and push $(IMAGE)"
	@echo "  make image-smoke      Run init-db/ingest/plot smoke test in container"
	@echo "  make print-image      Print current image ref"
	@echo ""
	@echo "Variables:"
	@echo "  CONTAINER_RUNTIME=$(CONTAINER_RUNTIME)"
	@echo "  IMAGE_REPO=$(IMAGE_REPO)"
	@echo "  TAG=$(TAG)"

image-build:
	$(CONTAINER_RUNTIME) build -t $(IMAGE) .

image-publish: image-build
	$(CONTAINER_RUNTIME) push $(IMAGE)

image-smoke:
	mkdir -p $(SMOKE_DIR)
	rm -f $(SMOKE_DB) $(SMOKE_HTML)
	printf '%s\n' \
	  'Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE' \
	  '2026-05-01,Push Day,3600,Bench Press,1,100,5,,,8' \
	  '2026-05-01,Push Day,3600,Bench Press,2,102.5,5,,,9' \
	  '2026-05-08,Push Day,3550,Bench Press,1,105,4,,,9' > $(SMOKE_CSV)
	$(CONTAINER_RUNTIME) run --rm -v $(SMOKE_DIR):$(SMOKE_MOUNT) $(IMAGE) --db $(SMOKE_MOUNT)/lifts-smoke.db init-db
	$(CONTAINER_RUNTIME) run --rm -v $(SMOKE_DIR):$(SMOKE_MOUNT) $(IMAGE) --db $(SMOKE_MOUNT)/lifts-smoke.db ingest --csv $(SMOKE_MOUNT)/strong-smoke.csv
	$(CONTAINER_RUNTIME) run --rm -v $(SMOKE_DIR):$(SMOKE_MOUNT) $(IMAGE) --db $(SMOKE_MOUNT)/lifts-smoke.db plot --exercise "$(SMOKE_EXERCISE)" --output $(SMOKE_MOUNT)/bench-smoke.html
	ls -lh $(SMOKE_HTML)

print-image:
	@echo $(IMAGE)
