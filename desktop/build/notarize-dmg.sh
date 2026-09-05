#!/usr/bin/env bash
#
# 解耦发布管道的第 2 阶段：在本地对签名的 dmg 进行公证。
#
# CI（第 1 阶段）已经生成了代码签名、强化运行时 dmg 和镜像
# 将它们视为未发布的 R2。 Apple 的公证服务保留了这个大型 PyInstaller
# 捆绑“进行中”几个小时，所以我们在这里进行公证——非 CI 时钟——并且
# 将票据直接钉在 dmg 上（用户下载即可运行）。
#
# 它对命令行上传递的每个 dmg 执行的操作：
#   1. 将 dmg 提交给公证服务 ONCE (--no-wait) 并记住 id，
#   2. 轮询该 SAME id，直到接受/无效；网络错误被忽略并且
#      重试，并且永远不会重新提交（避免堆积重复提交），
#   3. 将票据钉在 dmg 上，
#   4.（可选）将装订好的dmg重新上传到R2，覆盖未发布的
#      副本，因此 CDN 提供经过公证的字节。
#
# Auth：使用存储的钥匙串配置文件（默认值：cow-notary）。通过创建一次
#   xcrun notarytool store-credentials 牛公证人 \
#     --apple-id <id> --team-id <团队> --password <应用程序特定密码>
#
# 用途：
#   # 仅公证 + 订书钉（不上传）：
#   桌面/build/notarize-dmg.sh 路径/to/CowAgent-1.2.3-arm64.dmg [more.dmg ...]
#
#   # 公证 + 订书钉 + 重新上传到 R2（需要 wrangler + Cloudflare 信用）：
#   VER=1.2.3 上传=1 桌面/build/notarize-dmg.sh *.dmg
#
# 环境：
#   PROFILE 钥匙串配置文件名称（默认值：cow-notary）
#   UPLOAD 设置为 1 以将装订的 dmg 重新上传到 R2
#   R2 密钥桌面/v${VER}/<file> 的 VER 版本字符串（如果 UPLOAD=1，则为必需）
#   R2_BUCKET R2桶（默认：牛技能）
#   POLL_SECONDS 状态轮询间隔（默认值：60）
#   MAX_WAIT_MINUTES 在这么长的时间后放弃轮询（默认值：720 = 12h）
#
set -euo pipefail

PROFILE="${PROFILE:-cow-notary}"
R2_BUCKET="${R2_BUCKET:-cow-skills}"
POLL_SECONDS="${POLL_SECONDS:-60}"
MAX_WAIT_MINUTES="${MAX_WAIT_MINUTES:-720}"

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <dmg> [dmg ...]" >&2
  echo "  set UPLOAD=1 and VER=<version> to also re-upload stapled dmgs to R2" >&2
  exit 2
fi

if [ "${UPLOAD:-0}" = "1" ] && [ -z "${VER:-}" ]; then
  echo "error: UPLOAD=1 requires VER=<version> (used for the R2 key)" >&2
  exit 2
fi

log() { echo "[notarize-dmg] $*"; }

notarize_one() {
  local dmg="$1"
  if [ ! -f "$dmg" ]; then
    log "SKIP: not a file: $dmg"
    return 1
  fi

  # 如果它已经装订（例如重新运行），请直接跳到（可选）上传。
  if xcrun stapler validate "$dmg" >/dev/null 2>&1; then
    log "$dmg already stapled — skipping notarization."
  else
    log "submitting $dmg (no-wait)..."
    local submit_out submission_id
    submit_out="$(xcrun notarytool submit "$dmg" \
      --keychain-profile "$PROFILE" --no-wait --output-format json)"
    submission_id="$(echo "$submit_out" | /usr/bin/plutil -extract id raw - 2>/dev/null || true)"
    if [ -z "$submission_id" ] || [ "$submission_id" = "null" ]; then
      # 没有 plutil 的回退解析（json 是单行）。
      submission_id="$(echo "$submit_out" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')"
    fi
    if [ -z "$submission_id" ]; then
      log "ERROR: could not parse submission id from:"
      echo "$submit_out" >&2
      return 1
    fi
    log "submission id: $submission_id (polling same id, never resubmitting)"

    local deadline status ts
    deadline=$(( $(date +%s) + MAX_WAIT_MINUTES * 60 ))
    while :; do
      status=""
      status="$(xcrun notarytool info "$submission_id" \
        --keychain-profile "$PROFILE" --output-format json 2>/dev/null \
        | sed -n 's/.*"status":"\([^"]*\)".*/\1/p' || true)"
      ts="$(date +%H:%M:%S)"
      log "[$ts] status: ${status:-<query failed, retrying>}"

      case "$status" in
        Accepted) break ;;
        Invalid|Rejected)
          log "notarization $status — fetching log:"
          xcrun notarytool log "$submission_id" --keychain-profile "$PROFILE" || true
          return 1
          ;;
      esac

      if [ "$(date +%s)" -ge "$deadline" ]; then
        log "ERROR: not finished after ${MAX_WAIT_MINUTES} min (id: $submission_id)."
        log "NOT resubmitting. Check later: xcrun notarytool info $submission_id --keychain-profile $PROFILE"
        return 1
      fi
      sleep "$POLL_SECONDS"
    done

    log "Accepted; stapling ticket to $dmg"
    local staple_try=1
    until xcrun stapler staple "$dmg"; do
      if [ "$staple_try" -ge 3 ]; then
        log "ERROR: stapling failed after 3 attempts"
        return 1
      fi
      log "staple failed, retrying in 15s..."
      sleep 15
      staple_try=$((staple_try + 1))
    done
    xcrun stapler validate "$dmg"
    log "$dmg notarized + stapled."
  fi

  if [ "${UPLOAD:-0}" = "1" ]; then
    local base key
    base="$(basename "$dmg")"
    key="desktop/v${VER}/${base}"
    log "re-uploading stapled dmg -> r2://${R2_BUCKET}/${key}"
    npx --yes wrangler@latest r2 object put "${R2_BUCKET}/${key}" \
      --file "$dmg" --remote
    log "uploaded $base"
  fi
}

rc=0
for dmg in "$@"; do
  echo "======================================================================"
  notarize_one "$dmg" || rc=1
done

if [ "$rc" -ne 0 ]; then
  log "one or more dmgs failed — see output above."
  exit 1
fi
log "all done."
