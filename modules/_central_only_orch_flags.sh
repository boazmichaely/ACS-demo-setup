# Shared helpers for Central-only modules (impactPlanes: ["central"]).
# Orchestrator may still pass --plane / --secured-cluster-id; ignore gracefully.
# shellcheck shell=bash

central_only_handle_plane() {
  local prog="$1" val="$2"
  case "$val" in
    central) return 0 ;;
    openshift)
      echo "${prog}: Central-only module; ignoring --plane openshift" >&2
      return 0
      ;;
    *)
      echo "${prog}: Central-only module; --plane must be central (or omit); got ${val}" >&2
      return 1
      ;;
  esac
}

central_only_ignore_sc_id() {
  local prog="$1" id="$2"
  echo "${prog}: Central-only module; ignoring --secured-cluster-id ${id}" >&2
}
