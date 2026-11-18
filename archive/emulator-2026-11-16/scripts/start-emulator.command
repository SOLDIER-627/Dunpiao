#!/bin/zsh
set -euo pipefail

project_dir="${0:A:h:h}"
sdk_dir="$project_dir/.android-sdk"
avd_dir="$project_dir/.android-avd"
avd_name="Ticket_API35"
serial="emulator-5554"

export ANDROID_SDK_ROOT="$sdk_dir"
export ANDROID_AVD_HOME="$avd_dir"

adb="$sdk_dir/platform-tools/adb"
emulator="$sdk_dir/emulator/emulator"
config="$avd_dir/$avd_name.avd/config.ini"

if [[ ! -x "$adb" || ! -x "$emulator" || ! -f "$config" ]]; then
  print -u2 '模拟器组件缺失。请检查 Ticket 目录下的 .android-sdk 和 .android-avd。'
  exit 1
fi

# 硬件键盘必须在虚拟设备启动前启用。
if ! grep -q '^hw.keyboard=yes$' "$config"; then
  print -u2 '硬件键盘尚未启用：请把 config.ini 中的 hw.keyboard 改为 yes 后重启。'
  exit 1
fi

apply_preferences() {
  "$adb" -s "$serial" shell cmd overlay enable-exclusive --category com.android.internal.systemui.navbar.threebutton
  "$adb" -s "$serial" shell settings put secure show_ime_with_hard_keyboard 1
  locale_value="$("$adb" -s "$serial" shell getprop persist.sys.locale | tr -d '\r')"
  print '屏幕三键导航已启用；本机键盘已在虚拟设备配置中启用。'
  if [[ "$locale_value" == zh* ]]; then
    print "系统语言：$locale_value"
  else
    print -u2 "系统语言目前是 ${locale_value:-未知}；请在安卓设置中将简体中文置于语言列表首位。"
  fi
}

if [[ "$("$adb" -s "$serial" get-state 2>/dev/null || true)" == device ]]; then
  print '模拟器已经运行，正在确认导航和语言设置。'
  apply_preferences
  exit 0
fi

mkdir -p "$project_dir/logs"
log_file="$project_dir/logs/emulator.log"
print "正在启动 $avd_name；日志：$log_file"
"$emulator" "@$avd_name" -no-metrics -gpu swiftshader_indirect >> "$log_file" 2>&1 &
emulator_pid=$!

for (( attempt=1; attempt<=90; attempt++ )); do
  if [[ "$("$adb" -s "$serial" get-state 2>/dev/null || true)" == device ]] && \
     [[ "$("$adb" -s "$serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == 1 ]]; then
    apply_preferences
    print '模拟器已就绪。单击手机画面中的输入框后，即可使用 Mac 键盘输入。'
    wait "$emulator_pid" || true
    exit 0
  fi
  if ! kill -0 "$emulator_pid" 2>/dev/null; then
    print -u2 "模拟器启动失败，请查看 $log_file"
    wait "$emulator_pid" || true
    exit 1
  fi
  sleep 2
done

print -u2 "等待模拟器启动超时，请查看 $log_file"
exit 1
