import RPi.GPIO as GPIO
from time import sleep
import os
import signal
import sys
from datetime import datetime
import pytz

# Constants
GPIO_PIN = 12
PWM_FREQ = 100
CPU_TEMP_MIN = 43
EXT_TEMP_MIN = 31.5
CPU_TEMP_TRIGGER = 58
EXT_TEMP_TRIGGER = 33.6
TEMP_FULL = 65
EXT_TEMP_FULL = 33.8
CRITICAL_TEMP = 85
SHUTDOWN_DELAY = 5
BASE_POLL_INTERVAL = 10
FAST_POLL_INTERVAL = 2
EXT_SENSOR_ID = '28-00000b470aea'

FAN_OFF = 100
FAN_FULL = 0

# GPIO setup
GPIO.setmode(GPIO.BOARD)
GPIO.setwarnings(False)
GPIO.setup(GPIO_PIN, GPIO.OUT)
pwm = GPIO.PWM(GPIO_PIN, PWM_FREQ)
pwm.start(FAN_OFF)

last_duty_cycle = FAN_OFF
fan_active = False
critical_temp_time = None
fan_full_speed = False

# Time zone setup
dhaka_tz = pytz.timezone('Asia/Dhaka')

def get_formatted_time():
    return datetime.now(dhaka_tz).strftime("%Y-%m-%d %I:%M:%S %p")

def log_message(message):
    print(f"[{get_formatted_time()}] {message}")

def get_cpu_temp():
    with os.popen('vcgencmd measure_temp') as temp_file:
        return float(temp_file.read()[5:-3])

def get_external_temp():
    try:
        with open(f'/sys/bus/w1/devices/{EXT_SENSOR_ID}/w1_slave', 'r') as f:
            lines = f.readlines()
        return float(lines[1].split('=')[1]) / 1000 if lines[0].strip()[-3:] == 'YES' else None
    except (IOError, ValueError):
        return None

def calculate_duty_cycle(temp):
    if temp >= TEMP_FULL:
        return FAN_FULL
    elif temp <= CPU_TEMP_TRIGGER:
        return 0  # 50% speed when triggered
    return int(0 + (0 - FAN_FULL) * (TEMP_FULL - temp) / (TEMP_FULL - CPU_TEMP_TRIGGER))

def get_fan_speed_description(duty_cycle):
    if duty_cycle == FAN_OFF:
        return "OFF"
    elif duty_cycle == FAN_FULL:
        return "Full Speed"
    else:
        return f"{100 - duty_cycle}% speed"

def control_fan(cpu_temp, ext_temp):
    global last_duty_cycle, fan_active, critical_temp_time, fan_full_speed

    cpu_above_min = cpu_temp > CPU_TEMP_MIN
    ext_above_min = ext_temp > EXT_TEMP_MIN
    cpu_above_trigger = cpu_temp > CPU_TEMP_TRIGGER
    ext_above_trigger = ext_temp > EXT_TEMP_TRIGGER
    cpu_full = cpu_temp >= TEMP_FULL
    ext_full = ext_temp >= EXT_TEMP_FULL

    if cpu_full or ext_full:
        duty_cycle = FAN_FULL
        fan_full_speed = True
        trigger_reason = []
        if cpu_full:
            trigger_reason.append(f"CPU temperature ({cpu_temp:.1f}°C) reached full speed threshold ({TEMP_FULL}°C)")
        if ext_full:
            trigger_reason.append(f"External temperature ({ext_temp:.1f}°C) reached full speed threshold ({EXT_TEMP_FULL}°C)")
        reason = "Maximum temperature threshold reached: " + " and ".join(trigger_reason)
    elif fan_full_speed and not cpu_above_min and not ext_above_min:
        fan_full_speed = False
        duty_cycle = FAN_OFF
        reason = f"Temperatures dropped below minimum thresholds: CPU ({cpu_temp:.1f}°C) ≤ {CPU_TEMP_MIN}°C, External ({ext_temp:.1f}°C) ≤ {EXT_TEMP_MIN}°C"
    elif fan_full_speed:
        duty_cycle = FAN_FULL
        reason = "Maintaining full speed until temperatures drop below minimum thresholds"
    elif cpu_above_trigger or ext_above_trigger or (fan_active and (cpu_above_min or ext_above_min)):
        max_temp = max(cpu_temp, ext_temp)
        duty_cycle = calculate_duty_cycle(max_temp)
        fan_active = True
        trigger_reason = []
        if cpu_above_trigger:
            trigger_reason.append(f"CPU temperature ({cpu_temp:.1f}°C) above trigger point ({CPU_TEMP_TRIGGER}°C)")
        if ext_above_trigger:
            trigger_reason.append(f"External temperature ({ext_temp:.1f}°C) above trigger point ({EXT_TEMP_TRIGGER}°C)")
        if not (cpu_above_trigger or ext_above_trigger):
            trigger_reason.append("Maintaining active state (above minimum thresholds)")
        reason = "Fan active: " + " and ".join(trigger_reason)
    else:
        duty_cycle = FAN_OFF
        fan_active = False
        reason = f"Both temperatures below minimum thresholds: CPU ({cpu_temp:.1f}°C) ≤ {CPU_TEMP_MIN}°C, External ({ext_temp:.1f}°C) ≤ {EXT_TEMP_MIN}°C"

    fan_status = get_fan_speed_description(duty_cycle)

    if duty_cycle != last_duty_cycle:
        pwm.ChangeDutyCycle(duty_cycle)
        log_message(f"Fan status changed to: {fan_status}")
        log_message(f"Reason: {reason}")
        last_duty_cycle = duty_cycle
    else:
        log_message(f"Fan status: {fan_status}")
        log_message(f"Reason: {reason}")
    
    log_message(f"CPU Temperature: {cpu_temp:.1f}°C, External Temperature: {ext_temp:.1f}°C")
    
    if max(cpu_temp, ext_temp) >= CRITICAL_TEMP:
        handle_critical_temp(max(cpu_temp, ext_temp))
    elif critical_temp_time is not None:
        critical_temp_time = None
        log_message("Temperature dropped below critical. Shutdown cancelled.")

def handle_critical_temp(temp):
    global critical_temp_time
    current_time = datetime.now(dhaka_tz)
    
    if critical_temp_time is None:
        critical_temp_time = current_time
        log_message(f"CRITICAL: Temperature reached {temp:.1f}°C. Shutdown in {SHUTDOWN_DELAY} seconds.")
    elif (current_time - critical_temp_time).total_seconds() >= SHUTDOWN_DELAY:
        log_message(f"CRITICAL temperature exceeded. Initiating shutdown...")
        os.system("sudo shutdown -h now")
    else:
        remaining = SHUTDOWN_DELAY - int((current_time - critical_temp_time).total_seconds())
        log_message(f"CRITICAL: Temperature at {temp:.1f}°C. Shutdown in {remaining} seconds.")

def adaptive_poll_interval(cpu_temp, ext_temp):
    interval = FAST_POLL_INTERVAL if max(cpu_temp, ext_temp) >= TEMP_FULL or ext_temp >= EXT_TEMP_FULL else BASE_POLL_INTERVAL
    log_message(f"Next temperature check in {interval} seconds")
    return interval

def cleanup():
    pwm.stop()
    GPIO.cleanup()
    log_message("Fan control script terminated. GPIO cleaned up.")

def handle_shutdown(signum, frame):
    log_message(f"Received shutdown signal: {signal.Signals(signum).name}")
    cleanup()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGHUP, handle_shutdown)

log_message("Fan control script started.")
log_message(f"Configuration: CPU_MIN_TEMP={CPU_TEMP_MIN}°C, CPU_TRIGGER_TEMP={CPU_TEMP_TRIGGER}°C, "
            f"EXT_MIN_TEMP={EXT_TEMP_MIN}°C, EXT_TRIGGER_TEMP={EXT_TEMP_TRIGGER}°C, "
            f"CPU_FULL_SPEED_TEMP={TEMP_FULL}°C, EXT_FULL_SPEED_TEMP={EXT_TEMP_FULL}°C, "
            f"CRITICAL_TEMP={CRITICAL_TEMP}°C, SHUTDOWN_DELAY={SHUTDOWN_DELAY}s, "
            f"EXT_SENSOR_ID={EXT_SENSOR_ID}")

try:
    while True:
        cpu_temp = get_cpu_temp()
        ext_temp = get_external_temp()
        if ext_temp is None:
            log_message("WARNING: Unable to read external temperature. Using CPU temperature as fallback.")
            ext_temp = cpu_temp
        control_fan(cpu_temp, ext_temp)
        interval = adaptive_poll_interval(cpu_temp, ext_temp)
        sleep(interval)
except KeyboardInterrupt:
    log_message("Keyboard interrupt received. Terminating script.")
    cleanup()
