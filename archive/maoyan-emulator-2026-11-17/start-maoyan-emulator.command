#!/bin/zsh
set -euo pipefail

project_dir="${0:A:h:h}"
sdk_dir="$project_dir/.android-sdk"
avd_dir="$project_dir/.android-avd"
avd_name="Ticket_Maoyan_API35"
serial="emulator-5554"

export ANDROID_SDK_ROOT="$sdk_dir"
export ANDROID_AVD_HOME="$avd_dir"

adb="$sdk_dir/platform-tools/adb"
emulator="$sdk_dir/emulator/emulator"
config="$avd_dir/$avd_name.avd/config.ini"

if [[ ! -x "$adb" || ! -x "$emulator" || ! -f "$config" ]]; then
  print -u2 '猫眼模拟器尚未安装完成；请查看 docs/setup/猫眼模拟器恢复与使用.md。'
  exit 1
fi

if ! grep -q '^hw.keyboard=yes$' "$config"; then
  print -u2 'AVD 的 hw.keyboard 不是 yes，无法使用 Mac 键盘输入。'
  exit 1
fi

apply_preferences() {
  "$adb" -s "$serial" shell cmd overlay enable-exclusive --category com.android.internal.systemui.navbar.threebutton >/dev/null
  "$adb" -s "$serial" shell settings put secure show_ime_with_hard_keyboard 1
  locale_value="$("$adb" -s "$serial" shell getprop persist.sys.locale | tr -d '\r')"
  print "三键导航与 Mac 键盘已启用。当前系统语言：${locale_value:-未知}"
  if [[ "$locale_value" != zh* ]]; then
    print '如需简体中文，请在模拟器“设置 → 系统 → 语言”中将简体中文置顶。'
  fi
}

if [[ "$("$adb" -s "$serial" get-state 2>/dev/null || true)" == device ]]; then
  print '猫眼模拟器已运行。'
  apply_preferences
  exit 0
fi

mkdir -p "$project_dir/logs"
log_file="$project_dir/logs/maoyan-emulator.log"
print "正在启动 $avd_name；运行日志：$log_file"
"$emulator" "@$avd_name" -port 5554 -no-metrics -gpu swiftshader_indirect >> "$log_file" 2>&1 &
emulator_pid=$!

for (( attempt=1; attempt<=120; attempt++ )); do
  if [[ "$("$adb" -s "$serial" get-state 2>/dev/null || true)" == device ]] && \
     [[ "$("$adb" -s "$serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == 1 ]]; then
    apply_preferences
    print '模拟器已启动。请从 Google Play 安装猫眼 App 并人工登录。'
    wait "$emulator_pid" || true
    exit 0
  fi
  if ! kill -0 "$emulator_pid" 2>/dev/null; then
    print -u2 "模拟器启动失败，见 $log_file"
    wait "$emulator_pid" || true
    exit 1
  fi
  sleep 2
done

print -u2 "等待模拟器启动超时，见 $log_file"
exit 1
