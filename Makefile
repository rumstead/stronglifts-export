SHELL := /bin/bash

CONTAINER_RUNTIME ?= docker
IMAGE_REPO ?= ghcr.io/<your-github-user>/lifting-data
TAG ?= $(shell date +%Y%m%d-%H%M%S)
IMAGE ?= $(IMAGE_REPO):$(TAG)
LATEST_IMAGE ?= $(IMAGE_REPO):latest
SMOKE_CSV ?= /tmp/strong-smoke.csv
SMOKE_DB ?= /tmp/lifts-smoke.db
SMOKE_HTML ?= /tmp/bench-smoke.html
SMOKE_EXERCISE ?= Bench Press

.PHONY: help image-build image-push image-publish image-tag-latest image-smoke print-image

help:
	@echo "Targets:"
	@echo "  make image-build      Build $(IMAGE)"
	@echo "  make image-push       Push $(IMAGE)"
	@echo "  make image-tag-latest Tag/push latest in addition to $(IMAGE)"
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

image-push:
	$(CONTAINER_RUNTIME) push $(IMAGE)

image-tag-latest:
	$(CONTAINER_RUNTIME) tag $(IMAGE) $(LATEST_IMAGE)
	$(CONTAINER_RUNTIME) push $(LATEST_IMAGE)

image-publish: image-build image-push

image-smoke:
	printf '%s\n' \
	  'Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE' \
	  '2026-05-01,Push Day,3600,Bench Press,1,100,5,,,8' \
	  '2026-05-01,Push Day,3600,Bench Press,2,102.5,5,,,9' \
	  '2026-05-08,Push Day,3550,Bench Press,1,105,4,,,9' > $(SMOKE_CSV)
	$(CONTAINER_RUNTIME) run --rm -v $(SMOKE_CSV):$(SMOKE_CSV) $(IMAGE) --db $(SMOKE_DB) init-db
	$(CONTAINER_RUNTIME) run --rm -v $(SMOKE_CSV):$(SMOKE_CSV) $(IMAGE) --db $(SMOKE_DB) ingest --csv $(SMOKE_CSV)
	$(CONTAINER_RUNTIME) run --rm -v /tmp:/tmp $(IMAGE) --db $(SMOKE_DB) plot --exercise "$(SMOKE_EXERCISE)" --output $(SMOKE_HTML)
	ls -lh $(SMOKE_HTML)

print-image:
	@echo $(IMAGE)
