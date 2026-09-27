# Buildx isolated-config repair evidence

The image script's temporary `DOCKER_CONFIG` hid the installed Docker CLI plugin and the selected Docker context. The observed failure was `docker: unknown command: docker buildx` after `Login Succeeded`; Docker Buildx v0.37.1 worked with the normal config and failed with an empty config. Context metadata reported `desktop-linux` with endpoint `unix:///Users/desmondchyezhihao/.docker/run/docker.sock` without connecting to the daemon.

The script now stages the discovered Buildx executable and links the existing context metadata into its temporary config. It preserves explicit `DOCKER_CONTEXT` and `DOCKER_HOST` values; otherwise it pins the previously selected context. A daemon-free Buildx version preflight runs before ECR login, and the existing exit trap removes temporary state after failure.

Verification on 2026-09-27:

- `bash -n src/infra/scripts/build-and-publish-images.sh` passed.
- `python3 -m unittest discover -s tests/infra` passed (32 tests), including isolated-config discovery/context preservation with a relative source config path and a preflight failure case that proves ECR login does not start and temporary config is cleaned up.
- With a fresh temporary config staged as the script does, `docker buildx version` reported `github.com/docker/buildx v0.37.1 ...`; `docker context show` reported `desktop-linux`; and `docker context inspect` returned the same endpoint, `unix:///Users/desmondchyezhihao/.docker/run/docker.sock`, from both the normal and temporary configs. These are CLI metadata checks only; no daemon connection or image publish was attempted.
