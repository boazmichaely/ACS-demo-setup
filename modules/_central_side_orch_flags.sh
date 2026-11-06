# Shared helpers for Central-side modules that may use central-api and/or
# central-ocp (never secured-cluster). Ignore SC fan-out noise gracefully.
# shellcheck shell=bash

central_side_handle_plane() {
  local prog="$1" val="$2"
  case "$val" in
    central-api|central-ocp) return 0 ;;
    central)
      # legacy alias → treat as central-api
      return 0
      ;;
    secured-cluster|openshift)
      echo "${prog}: Central-side module; ignoring --plane ${val}" >&2
      return 0
      ;;
    *)
      echo "${prog}: Central-side module; --plane must be central-api or central-ocp (or omit); got ${val}" >&2
      return 1
      ;;
  esac
}

central_side_ignore_sc_id() {
  local prog="$1" id="$2"
  echo "${prog}: Central-side module; ignoring --secured-cluster-id ${id}" >&2
}
