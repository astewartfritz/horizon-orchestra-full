#!/usr/bin/env bash
# deploy.sh — Deployment script for Horizon Orchestra.
# Builds Docker image, pushes to registry, updates Kubernetes or docker-compose,
# performs health check after deploy, and rolls back on failure.
set -euo pipefail

# --- Configuration ---
IMAGE_NAME="${IMAGE_NAME:-horizon-orchestra}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo "latest")}"
REGISTRY="${DOCKER_REGISTRY:-ghcr.io/astewartfritz}"
FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
DEPLOY_MODE="${DEPLOY_MODE:-docker-compose}"  # "kubernetes" or "docker-compose"
K8S_NAMESPACE="${K8S_NAMESPACE:-orchestra}"
K8S_DEPLOYMENT="${K8S_DEPLOYMENT:-orchestra}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
HEALTH_CHECK_URL="${HEALTH_CHECK_URL:-http://localhost:8081/healthz}"
HEALTH_CHECK_RETRIES="${HEALTH_CHECK_RETRIES:-30}"
HEALTH_CHECK_INTERVAL="${HEALTH_CHECK_INTERVAL:-5}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREVIOUS_TAG=""

log_info()  { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [INFO]  $*"; }
log_error() { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [ERROR] $*" >&2; }
log_warn()  { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [WARN]  $*"; }

# --- Build Docker image ---
build_image() {
    log_info "Building Docker image: ${FULL_IMAGE}"

    docker build \
        --tag "${FULL_IMAGE}" \
        --tag "${REGISTRY}/${IMAGE_NAME}:latest" \
        --build-arg "BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
        --build-arg "VCS_REF=${IMAGE_TAG}" \
        --file Dockerfile \
        . || {
        log_error "Docker build failed"
        exit 1
    }

    log_info "Docker image built successfully"
}

# --- Push to registry ---
push_image() {
    log_info "Pushing image to registry: ${FULL_IMAGE}"

    docker push "${FULL_IMAGE}" || {
        log_error "Failed to push ${FULL_IMAGE}"
        exit 1
    }

    docker push "${REGISTRY}/${IMAGE_NAME}:latest" || {
        log_warn "Failed to push latest tag (non-fatal)"
    }

    log_info "Image pushed successfully"
}

# --- Deploy with Kubernetes ---
deploy_kubernetes() {
    log_info "Deploying to Kubernetes (namespace: ${K8S_NAMESPACE})"

    # Record current image for rollback.
    PREVIOUS_TAG=$(kubectl get deployment "${K8S_DEPLOYMENT}" \
        -n "${K8S_NAMESPACE}" \
        -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo "")

    log_info "Previous image: ${PREVIOUS_TAG:-none}"

    # Update the deployment image.
    kubectl set image "deployment/${K8S_DEPLOYMENT}" \
        "${IMAGE_NAME}=${FULL_IMAGE}" \
        -n "${K8S_NAMESPACE}" || {
        log_error "kubectl set image failed"
        return 1
    }

    # Wait for rollout.
    log_info "Waiting for rollout to complete"
    if ! kubectl rollout status "deployment/${K8S_DEPLOYMENT}" \
        -n "${K8S_NAMESPACE}" \
        --timeout=300s; then
        log_error "Rollout did not complete in time"
        return 1
    fi

    log_info "Kubernetes deployment updated"
}

# --- Deploy with docker-compose ---
deploy_compose() {
    log_info "Deploying with docker-compose"

    if [[ ! -f "${COMPOSE_FILE}" ]]; then
        log_error "Compose file not found: ${COMPOSE_FILE}"
        return 1
    fi

    # Record current image for rollback.
    PREVIOUS_TAG=$(docker-compose -f "${COMPOSE_FILE}" ps -q orchestra 2>/dev/null || echo "")

    # Pull and recreate.
    IMAGE="${FULL_IMAGE}" docker-compose -f "${COMPOSE_FILE}" pull
    IMAGE="${FULL_IMAGE}" docker-compose -f "${COMPOSE_FILE}" up -d --force-recreate || {
        log_error "docker-compose up failed"
        return 1
    }

    log_info "docker-compose deployment updated"
}

# --- Health check after deploy ---
health_check() {
    log_info "Running post-deploy health check (${HEALTH_CHECK_RETRIES} retries, ${HEALTH_CHECK_INTERVAL}s interval)"

    for i in $(seq 1 "${HEALTH_CHECK_RETRIES}"); do
        if curl -sf --max-time 5 "${HEALTH_CHECK_URL}" &>/dev/null; then
            log_info "Health check passed (attempt ${i}/${HEALTH_CHECK_RETRIES})"
            return 0
        fi
        log_warn "Health check attempt ${i}/${HEALTH_CHECK_RETRIES} failed, retrying in ${HEALTH_CHECK_INTERVAL}s"
        sleep "${HEALTH_CHECK_INTERVAL}"
    done

    log_error "Health check failed after ${HEALTH_CHECK_RETRIES} attempts"
    return 1
}

# --- Rollback ---
rollback() {
    log_error "Deployment failed, initiating rollback"

    if [[ "${DEPLOY_MODE}" == "kubernetes" ]]; then
        log_info "Rolling back Kubernetes deployment"
        kubectl rollout undo "deployment/${K8S_DEPLOYMENT}" -n "${K8S_NAMESPACE}" || {
            log_error "Kubernetes rollback failed!"
            exit 2
        }
        kubectl rollout status "deployment/${K8S_DEPLOYMENT}" \
            -n "${K8S_NAMESPACE}" --timeout=120s || true
        log_info "Kubernetes rollback complete"

    elif [[ "${DEPLOY_MODE}" == "docker-compose" ]]; then
        if [[ -n "${PREVIOUS_TAG}" ]]; then
            log_info "Rolling back docker-compose to previous version"
            IMAGE="${PREVIOUS_TAG}" docker-compose -f "${COMPOSE_FILE}" up -d --force-recreate || {
                log_error "docker-compose rollback failed!"
                exit 2
            }
            log_info "docker-compose rollback complete"
        else
            log_error "No previous version to rollback to"
            exit 2
        fi
    fi
}

# --- Main ---
log_info "=== Horizon Orchestra Deployment ==="
log_info "Image:  ${FULL_IMAGE}"
log_info "Mode:   ${DEPLOY_MODE}"
log_info "Health: ${HEALTH_CHECK_URL}"

# Step 1: Build.
build_image

# Step 2: Push.
push_image

# Step 3: Deploy.
DEPLOY_OK=true
if [[ "${DEPLOY_MODE}" == "kubernetes" ]]; then
    deploy_kubernetes || DEPLOY_OK=false
elif [[ "${DEPLOY_MODE}" == "docker-compose" ]]; then
    deploy_compose || DEPLOY_OK=false
else
    log_error "Unknown DEPLOY_MODE: ${DEPLOY_MODE}"
    exit 1
fi

if ! ${DEPLOY_OK}; then
    rollback
    exit 1
fi

# Step 4: Health check.
if ! health_check; then
    rollback
    exit 1
fi

log_info "=== Deployment successful ==="
log_info "Image:     ${FULL_IMAGE}"
log_info "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
