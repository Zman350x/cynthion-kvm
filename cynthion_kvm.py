#!/bin/env python3

import evdev, re, time, asyncio
from facedancer.devices.keyboard import USBKeyboardDevice
from facedancer.errors import EndEmulation
from evdev_facedancer_mapping import ev_face_map, ev_face_modifier_map

FIFO = "/tmp/active_window"
WINDOW_POLLING = 100

last_read_time = 0
last_active_window = False

# For sorting natural sorting of device paths
def device_path_key(device):
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r'(\d+)', device.path)]

def flush_input(device):
    time.sleep(0.1)
    try:
        for event in device.read():
            pass
    except BlockingIOError:
        pass


# Show list of devices and get which the user wants to use as keyboard
def device_prompt():
    devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    devices.sort(key=device_path_key)

    print("ID    PATH                NAME")
    for id, device in enumerate(devices):
        print(f"{id:<5} {device.path:<20} {device.name}")

    while True:
        id = input("Choose device ID to forward to cynthion: ")
        try:
            id = int(id)
            if id >= 0 and id < len(devices):
                break
            print("Invalid ID, try again")
        except ValueError:
            print("Invalid ID, try again")

    # Return chosen device
    return devices[id]

# Milliseconds since epoch
def millis():
    return time.time_ns() // 1000000

# Returns true if the FIFO contains a 0
def is_active_window():
    global last_read_time, last_active_window

    if millis() - last_read_time > WINDOW_POLLING:
        last_read_time = millis()
        with open(FIFO, 'r') as file:
            try:
                last_active_window = file.read() == "0"
            except TypeError:
                last_active_window = False
    return last_active_window

# Blocks input if on active window and forwards to facedancer
# Numpad keys not blocked (sent as a pulse to host on key up)
# Numpad minus on active window exits program
async def forward_device(host_device, target_device):
    ui = evdev.UInput.from_device(host_device)

    flush_input(host_device)

    with host_device.grab_context():
        while is_active_window():
            event = host_device.read_one()
            if event is None or event.type != evdev.ecodes.EV_KEY:
                continue

            key_event = evdev.KeyEvent(event)
            if (key_event.scancode == evdev.ecodes.KEY_NUMLOCK or
                  key_event.keycode.startswith("KEY_KP")):
                if key_event.keystate == evdev.KeyEvent.key_up:
                    if key_event.scancode == evdev.ecodes.KEY_KPMINUS:
                        return True
                    # Forward numpad keys
                    ui.write(event.type, event.code,
                             evdev.KeyEvent.key_down)
                    ui.write(event.type, event.code,
                             evdev.KeyEvent.key_up)
                    ui.syn()
            else:
                if key_event.keystate == evdev.KeyEvent.key_down:
                    try:
                        if ((k := ev_face_modifier_map.get(key_event.scancode))
                                is not None):
                            target_device.modifier_down(k)
                        target_device.key_down(ev_face_map[key_event.scancode])
                    except KeyError:
                        pass
                elif key_event.keystate == evdev.KeyEvent.key_up:
                    try:
                        if ((k := ev_face_modifier_map.get(key_event.scancode))
                                is not None):
                            target_device.modifier_up(k)
                        target_device.key_up(ev_face_map[key_event.scancode])
                    except KeyError:
                        pass
            await asyncio.sleep(0)
    return False

async def host_routine(host_device, target_device):
    while True:
        if is_active_window():
            do_quit = await forward_device(host_device, target_device)
            if do_quit:
                raise EndEmulation
                return

def main():
    host_device = device_prompt()
    target_device = USBKeyboardDevice()
    target_device.emulate(host_routine(host_device, target_device))

if __name__ == "__main__":
    main()
