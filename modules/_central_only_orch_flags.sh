# Shared helpers for central-api-only modules (impactPlanes: ["central-api"]).
# Orchestrator may still pass --plane / --secured-cluster-id; ignore gracefully.
# shellcheck shell=bash

central_only_handle_plane() {
  local prog="$1" val="$2"
  case "$val" in
    central-api|central)
      # ``central`` accepted as legacy alias for central-api
      return 0
      ;;
    secured-cluster|openshift)
      echo "${prog}: central-api-only module; ignoring --plane ${val}" >&2
      return 0
      ;;
    central-ocp)
      echo "${prog}: central-api-only module; ignoring --plane central-ocp" >&2
      return 0
      ;;
    *)
      echo "${prog}: central-api-only module; --plane must be central-api (or omit); got ${val}" >&2
      return 1
      ;;
  esac
}

central_only_ignore_sc_id() {
  local prog="$1" id="$2"
  echo "${prog}: central-api-only module; ignoring --secured-cluster-id ${id}" >&2
}
