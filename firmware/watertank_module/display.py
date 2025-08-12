"""Display module for ESP32-S3-BOX-3 touch screen.

Provides a simple UI for showing water tank level, status, and log messages
on the built-in capacitive touch screen of the ESP32-S3-BOX-3.
"""

import lvgl as lv
import time
from machine import Timer

class WaterTankDisplay:
    """Display manager for ESP32-S3-BOX-3 touch screen."""
    
    def __init__(self, config=None):
        """Initialize the display and create UI elements.
        
        Args:
            config: Configuration dictionary with display settings
        """
        self.config = config or {}
        self.screen = lv.obj()
        self.tank_level_bar = None
        self.status_label = None
        self.level_label = None
        self.log_area = None
        self.log_messages = []
        self.max_log_lines = 8
        
        # Apply configuration
        self._apply_config()
        self._setup_ui()
        self._setup_timer()
    
    def _apply_config(self):
        """Apply display configuration settings."""
        # Set display brightness if supported
        try:
            brightness = self.config.get("display_brightness", 50)
            if hasattr(lv, 'set_brightness'):
                lv.set_brightness(brightness)
        except Exception:
            pass
        
        # Set timeout if configured
        self.timeout_s = self.config.get("display_timeout_s", 0)
        self.last_activity = time.time()
    
    def _setup_ui(self):
        """Create and configure UI elements."""
        # Main container
        container = lv.obj(self.screen)
        container.set_size(320, 240)
        container.center()
        container.set_style_bg_color(lv.color_hex(0x000000), 0)
        
        # Title
        title = lv.label(container)
        title.set_text("WaterTank Monitor")
        title.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        title.set_style_text_font(lv.font_montserrat_16, 0)
        title.align(lv.ALIGN_TOP_MID, 0, 10)
        
        # Tank level bar
        self.tank_level_bar = lv.bar(container)
        self.tank_level_bar.set_size(280, 30)
        self.tank_level_bar.align(lv.ALIGN_TOP_MID, 0, 50)
        self.tank_level_bar.set_range(0, 100)
        self.tank_level_bar.set_value(0, lv.ANIM_ON)
        
        # Level percentage label
        self.level_label = lv.label(container)
        self.level_label.set_text("0%")
        self.level_label.set_style_text_color(lv.color_hex(0x00FF00), 0)
        self.level_label.set_style_text_font(lv.font_montserrat_20, 0)
        self.level_label.align(lv.ALIGN_TOP_MID, 0, 90)
        
        # Status label
        self.status_label = lv.label(container)
        self.status_label.set_text("Initializing...")
        self.status_label.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        self.status_label.set_style_text_font(lv.font_montserrat_14, 0)
        self.status_label.align(lv.ALIGN_TOP_MID, 0, 120)
        
        # Log area
        log_container = lv.obj(container)
        log_container.set_size(300, 100)
        log_container.align(lv.ALIGN_TOP_MID, 0, 150)
        log_container.set_style_bg_color(lv.color_hex(0x222222), 0)
        log_container.set_style_border_color(lv.color_hex(0x444444), 0)
        log_container.set_style_border_width(1, 0)
        
        self.log_area = lv.label(log_container)
        self.log_area.set_size(290, 90)
        self.log_area.align(lv.ALIGN_TOP_LEFT, 5, 5)
        self.log_area.set_style_text_color(lv.color_hex(0xCCCCCC), 0)
        self.log_area.set_style_text_font(lv.font_montserrat_12, 0)
        self.log_area.set_text("Starting up...")
    
    def _setup_timer(self):
        """Setup timer for periodic UI updates."""
        self.timer = Timer(0)
        self.timer.init(period=1000, mode=Timer.PERIODIC, callback=self._update_display)
    
    def _update_display(self, timer):
        """Periodic display update callback."""
        try:
            lv.task_handler()
            
            # Handle display timeout if configured
            if self.timeout_s > 0:
                if time.time() - self.last_activity > self.timeout_s:
                    # Dim or turn off display
                    if hasattr(lv, 'set_brightness'):
                        lv.set_brightness(10)  # Very dim
        except Exception as e:
            print(f"Display update error: {e}")
    
    def _update_activity(self):
        """Update last activity timestamp and restore brightness."""
        self.last_activity = time.time()
        if self.timeout_s > 0 and hasattr(lv, 'set_brightness'):
            brightness = self.config.get("display_brightness", 50)
            lv.set_brightness(brightness)
    
    def update_tank_level(self, level_pct, level_mm=None):
        """Update the tank level display.
        
        Args:
            level_pct: Water level as percentage (0-100)
            level_mm: Water level in millimeters (optional)
        """
        self._update_activity()
        
        if self.tank_level_bar:
            self.tank_level_bar.set_value(int(level_pct), lv.ANIM_ON)
        
        if self.level_label:
            if level_mm is not None:
                self.level_label.set_text(f"{level_pct:.1f}% ({level_mm:.0f}mm)")
            else:
                self.level_label.set_text(f"{level_pct:.1f}%")
            
            # Color coding based on level
            if level_pct <= 10:
                self.level_label.set_style_text_color(lv.color_hex(0xFF0000), 0)  # Red
            elif level_pct <= 30:
                self.level_label.set_style_text_color(lv.color_hex(0xFF8800), 0)  # Orange
            else:
                self.level_label.set_style_text_color(lv.color_hex(0x00FF00), 0)  # Green
    
    def update_status(self, status, color=None):
        """Update the status display.
        
        Args:
            status: Status message string
            color: Hex color code (optional, defaults to yellow)
        """
        self._update_activity()
        
        if self.status_label:
            self.status_label.set_text(status)
            if color:
                self.status_label.set_style_text_color(lv.color_hex(color), 0)
            else:
                self.status_label.set_style_text_color(lv.color_hex(0xFFFF00), 0)
    
    def add_log_message(self, message, level="info"):
        """Add a log message to the display.
        
        Args:
            message: Log message string
            level: Log level ("err", "warn", "info")
        """
        self._update_activity()
        
        timestamp = time.localtime()
        time_str = f"{timestamp[3]:02d}:{timestamp[4]:02d}"
        
        # Color coding for log levels
        if level == "err":
            color = 0xFF0000  # Red
        elif level == "warn":
            color = 0xFF8800  # Orange
        else:
            color = 0x00FF00  # Green
        
        log_entry = f"[{time_str}] {message}"
        self.log_messages.append((log_entry, color))
        
        # Keep only the last N messages
        if len(self.log_messages) > self.max_log_lines:
            self.log_messages.pop(0)
        
        # Update display
        self._update_log_display()
    
    def _update_log_display(self):
        """Update the log area display."""
        if not self.log_area:
            return
        
        # Combine all log messages
        display_text = ""
        for msg, color in self.log_messages:
            display_text += msg + "\n"
        
        self.log_area.set_text(display_text.strip())
    
    def show_screen(self):
        """Show the display screen."""
        lv.scr_load(self.screen)
    
    def cleanup(self):
        """Clean up display resources."""
        if hasattr(self, 'timer'):
            self.timer.deinit()
        lv.deinit()

# Global display instance
_display = None

def get_display(config=None):
    """Get or create the global display instance.
    
    Args:
        config: Configuration dictionary with display settings
    """
    global _display
    if _display is None:
        try:
            _display = WaterTankDisplay(config)
            _display.show_screen()
        except Exception as e:
            print(f"Display init failed: {e}")
            _display = None
    return _display

def update_tank_level(level_pct, level_mm=None):
    """Update tank level on display if available."""
    display = get_display()
    if display:
        display.update_tank_level(level_pct, level_mm)

def update_status(status, color=None):
    """Update status on display if available."""
    display = get_display()
    if display:
        display.update_status(status, color)

def add_log_message(message, level="info"):
    """Add log message to display if available."""
    display = get_display()
    if display:
        display.add_log_message(message, level)
