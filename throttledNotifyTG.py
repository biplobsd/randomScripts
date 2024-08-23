import subprocess
import argparse
from time import sleep
import telegram_send
import asyncio

def get_throttled_state():
    output = subprocess.check_output(["vcgencmd", "get_throttled"]).decode("utf-8").strip()
    throttled_hex = output.split('=')[1]
    return throttled_hex, int(throttled_hex, 16)

def interpret_throttled_state(state):
    messages = []
    if state & 0x1:
        messages.append("Under-voltage detected")
    if state & 0x2:
        messages.append("ARM frequency capped")
    if state & 0x4:
        messages.append("Currently throttled")
    if state & 0x8:
        messages.append("Soft temperature limit active")
    if state & 0x10000:
        messages.append("Under-voltage has occurred")
    if state & 0x20000:
        messages.append("ARM frequency capping has occurred")
    if state & 0x40000:
        messages.append("Throttling has occurred")
    if state & 0x80000:
        messages.append("Soft temperature limit has occurred")
    return messages

async def send_telegram_notification(throttled_hex, throttled_messages):
    notif_message = f"Throttling Alert! (0x{throttled_hex}):\n" + "\n".join(throttled_messages)
    try:
        await telegram_send.send(messages=[notif_message])
        print("Notification sent successfully")
    except Exception as e:
        print(f"ERROR: Failed to send notification - {str(e)}")

async def main(test_mode=False):
    if test_mode:
        print("Running in test mode")
        test_values = ["0x50000", "0x50005", "0x80008"]
        for test_hex in test_values:
            print(f"Testing with value: {test_hex}")
            test_state = int(test_hex, 16)
            test_messages = interpret_throttled_state(test_state)
            await send_telegram_notification(test_hex[2:], test_messages)
            await asyncio.sleep(10)  # Wait 10 seconds between test notifications
        print("Test mode completed")
    else:
        while True:
            await asyncio.sleep(5)
            throttled_hex, throttled_state = get_throttled_state()
            throttled_messages = interpret_throttled_state(throttled_state)
            
            if throttled_messages:
                await send_telegram_notification(throttled_hex, throttled_messages)
                await asyncio.sleep(60 * 6)  # Wait 6 minutes before checking again

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monitor Raspberry Pi throttling")
    parser.add_argument("--test", action="store_true", help="Run in test mode")
    args = parser.parse_args()
    
    asyncio.run(main(test_mode=args.test))