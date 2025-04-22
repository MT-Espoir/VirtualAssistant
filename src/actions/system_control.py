import os
import subprocess
import psutil
import time
import os

def control_volume(level=None, change=None):
    """
    Điều chỉnh âm lượng hệ thống
    
    Args:
        level: Mức âm lượng cụ thể (0-100)
        change: Thay đổi âm lượng (ví dụ: +10, -15)
    """
    try:
        if os.name == 'nt':  # Windows
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(
                IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            
            # Đặt âm lượng cụ thể (0-100)
            if level is not None:
                vol_level = max(0, min(100, level)) / 100.0
                volume.SetMasterVolumeLevelScalar(vol_level, None)
                return f"Volume set to {level}%"
            
            # Tăng/giảm âm lượng
            elif change is not None:
                current_vol = volume.GetMasterVolumeLevelScalar() * 100
                new_vol = max(0, min(100, current_vol + change)) / 100.0
                volume.SetMasterVolumeLevelScalar(new_vol, None)
                return f"Volume changed to {int(new_vol * 100)}%"
        
        return "Volume control is only supported on Windows"
    except Exception as e:
        return f"Error controlling volume: {e}"

def control_brightness(level=None, change=None):
    """Điều chỉnh độ sáng màn hình"""
    try:
        if os.name == 'nt':  # Windows
            import screen_brightness_control as sbc
            
            if level is not None:
                sbc.set_brightness(level)
                return f"Brightness set to {level}%"
            elif change is not None:
                current = sbc.get_brightness()[0]
                new_level = max(0, min(100, current + change))
                sbc.set_brightness(new_level)
                return f"Brightness changed to {new_level}%"
        
        return "Brightness control is only supported on Windows"
    except Exception as e:
        return f"Error controlling brightness: {e}"

def get_running_applications():
    """Get a list of all running user applications"""
    running_apps = []
    
    for proc in psutil.process_iter(['pid', 'name', 'username']):
        try:
            # Skip system processes
            if proc.info['username'] is None:
                continue
                
            if not any(sys_proc in proc.info['name'].lower() for sys_proc in 
                      ['svchost', 'system', 'registry', 'smss', 'csrss', 'wininit', 'services']):
                running_apps.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
            
    return running_apps

def close_all_applications():
    """Close all running user applications gracefully"""
    running_apps = get_running_applications()
    
    closed_count = 0
    for proc in running_apps:
        try:
            proc_name = proc.name()
            print(f"Closing application: {proc_name}")
            proc.terminate() 
            closed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            print(f"Could not close {proc_name}")
            
    time.sleep(2)
    
    # Force close any that didn't terminate gracefully
    for proc in psutil.process_iter():
        if proc in running_apps and proc.is_running():
            try:
                proc.kill() 
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
                
    return closed_count

def system_shutdown(close_apps=True):
    """Shutdown the system after closing applications"""
    if close_apps:
        closed_count = close_all_applications()
        print(f"Closed {closed_count} applications before shutdown")
    
    print("Shutting down system...")
    # Add a small delay to allow the message to be displayed
    time.sleep(1)
    
    # Execute system shutdown command
    os.system("shutdown /s /t 3 /c \"Voice Assistant: System shutdown requested\"")
    return "Shutting down your system now"

def system_restart(close_apps=True):
    """Restart the system after closing applications"""
    if close_apps:
        closed_count = close_all_applications()
        print(f"Closed {closed_count} applications before restart")
    
    print("Restarting system...")
    time.sleep(1)
    
    # Execute system restart command
    os.system("shutdown /r /t 3 /c \"Voice Assistant: System restart requested\"")
    return "Restarting your system now"