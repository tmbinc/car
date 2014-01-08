import gobject
import dbus, struct, sys
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop

DBusGMainLoop(set_as_default=True)

session_bus = dbus.SessionBus()
s12x = session_bus.get_object("com.nokia.s12xrouter", "/com/nokia/s12xrouter")
mainprovider = session_bus.get_object("com.nokia.appl.ui.mainprovider", "/com/nokia/appl/ui/mainprovider")
genericdisplay = session_bus.get_object("com.nokia.appl.ui.genericdisplay", "/com/nokia/appl/ui/genericdisplay")

def b(x):
  return x.replace(" ", "").decode('hex')

def KeyEventNotification(*args):
  print "KeyEventNotification", args

class NavPos(object):
  def NavPosNotification(*args):
    # NavPosNotification (dbus.Byte(10), dbus.Byte(2), dbus.Byte(43), dbus.Byte(75), dbus.Byte(53), dbus.Byte(0), dbus.Byte(53), dbus.Byte(66), dbus.Byte(3))

    # convert to signed degrees format; N/E is positive, W/S is negative
    long_degree, long_sign, long_min, long_minfrac, lat_degree, lat_sign, lat_min, lat_minfrac, fix = (int(x) for x in args)
  
    # Only tested N/E
    long_sign = {2: 1, 0: -1}[long_sign]
    lat_sign = {2: -1, 0: 1}[lat_sign]
  
    pos = (lat_sign * (lat_degree + lat_min / 60.0 + lat_minfrac / 6000.0), long_sign * (long_degree + long_min / 60.0 + long_minfrac / 6000.0))
    
    print "NavPos", pos
    self.last_pos = pos

nav_pos = NavPos()

s12x.connect_to_signal("KeyEventNotification", KeyEventNotification)
s12x.connect_to_signal("NavPosNotification", nav_pos.NavPosNotification)

class LogicalScreen(object):
  KEY_OK = 19
  KEY_UP = 14
  KEY_DOWN = 15
  KEY_BACK = 27
  
  FLAG_VISIBLE = 0x8000
  FLAG_ACTIVATED = 0x0800
  FLAG_SELECTED = 0x0400
  FLAG_FOCUSSED = 0x0200
  FLAG_SELECTABLE = 0x0100
  
  LINES_TOTAL = 4

  def __init__(self):
    self.closed = False
    self.changed = True
    self.timer = None
    self.result = None

  def render(self):
    self.changed = False
    return 2, [(0x8000, "no data"), (0, ""), (0, ""), (0, "")], 0, 0

  def key_event(self, key, state):
    if key == self.KEY_BACK:
      self.closed = True
    if key == self.KEY_UP:
      return Menu(["Key Up"], ["OK", "Nope", "maybe", "let's see", "never"])
    else:
      return None

  def returned(self, result):
    pass

class Menu(LogicalScreen):
  def __init__(self, message = [], choices = []):
    LogicalScreen.__init__(self)
    self.message = message
    self.choices = choices
    self.scroll_pos = 0
    self.current_choice = 0
  
  def render(self):
    res = []
    
    for i in self.message:
      res.append((0x8000, i))
    
    num_lines_left = self.LINES_TOTAL - len(res)
    
    index = self.scroll_pos
    
    for i in range(num_lines_left):
    
      if index >= len(self.choices):
        res.append((self.FLAG_VISIBLE, ""))
        continue
    
      flags = self.FLAG_VISIBLE
      flags |= self.FLAG_SELECTABLE
      
      if index == self.current_choice:
        flags |= self.FLAG_FOCUSSED
      
      res.append((flags, self.choices[index]))
      
      index += 1

    print self.scroll_pos, self.current_choice, res    
  
    return 2, res, self.scroll_pos, len(self.choices)
  
  def key_event(self, key, state):
  
    # ignore key up events
    if not state:
      return
    
    if key == self.KEY_OK:
      return self.selected(self.current_choice)
    if key == self.KEY_BACK:
      return self.selected(None)
    elif key == self.KEY_DOWN:
      if self.current_choice != len(self.choices) - 1:
        self.current_choice += 1
        self.changed = True
    elif key == self.KEY_UP:
      if self.current_choice != 0:
        self.current_choice -= 1
        self.changed = True
    
    choice_lines = self.LINES_TOTAL - len(self.message)
    if self.current_choice >= self.scroll_pos + choice_lines:
      self.scroll_pos += 1
    if self.current_choice < self.scroll_pos:
      self.scroll_pos -= 1

  def selected(self, choice):
    print "MENU default selected"
    self.closed = True
    self.result = choice

class BapDisplay(dbus.service.Object):
  def __init__(self, genericdisplay, s12x, root):
    self.genericdisplay = genericdisplay
    self.s12x = s12x
    bus_name = dbus.service.BusName('de.debugmo.helloworld', bus=dbus.SessionBus())
    dbus.service.Object.__init__(self, bus_name, '/de/debugmo/helloworld')
    self.dummy_screen_handle = None
    self.last_active_handle = None
    self.genericdisplay.connect_to_signal("ActiveHandleChangedNotification", self.ActiveHandleChangedNotification)
    s12x.connect_to_signal("KeyEventNotification", self.KeyEventNotification)
    self.visible = False
    self.wait_for_activation = True
    self.pending_destroy = False
    self.create_dummy_screen()
    
    self.screen_stack = [root]

  @dbus.service.method('de.debugmo.helloworld.request', in_signature="uuuiii")
  def SetLogicalKeyPressed(self, displayId, screenId, selectionId, logicalKey, action, value):
    print "SetLogicalKeyPressed displayId %s, screenId %s, selectionId %s, logicalKey %s, action %s, value %s" % ( hex(displayId), hex(screenId), hex(selectionId), hex(logicalKey), hex(action), hex(value))
  
  def KeyEventNotification(self, *args):
    if self.visible and len(self.screen_stack):
      print "For active display: KeyEventNotification", args
      
      update = False
      
      current_screen = self.screen_stack[-1]
      r = current_screen.key_event(args[2], args[1] == 0)
      
      if current_screen.closed:
        result = self.screen_stack.pop().result
        if len(self.screen_stack):
          self.screen_stack[-1].returned(result)
        update = True
      
      if r is not None:
        self.screen_stack.append(r)
        update = True
        
      print "screen event", self.screen_stack
      if not len(self.screen_stack):
        self.destroy()
      else:
        current_screen = self.screen_stack[-1]
        print current_screen.changed
        if current_screen.changed or update:
          self.update()
    else:
      print "ignoring"

  def ActiveHandleChangedNotification(self, active_handle):
    print "ACTIVE HANDLE CHANGED", active_handle
    if active_handle == self.dummy_screen_handle:
      if not self.visible:
        self.visible = True
        self.activate()
    else:
      if self.visible:
        self.visible = False
        self.deactivate()
      self.last_active_handle = active_handle
      
      if self.wait_for_activation:
        print "activating now"
        self.wait_for_activation = False
        self.force_screen_visible()
      
      if self.pending_destroy:
        print "pending destroy"
        self.destroy()
  
  def create_dummy_screen(self):
    self.dummy_screen_handle = genericdisplay.CreateHandle(["de.debugmo.helloworld", "/de/debugmo/helloworld", "de.debugmo.helloworld.request"])
    self.genericdisplay.SetData(self.dummy_screen_handle, 
      dbus.ByteArray("010000001500000000000000000000000200000000000000010000002a0000006e0000000100000002000000020000000100000057696e646f77732050686f6e6500010000002400000015000000020000000100000001000000020000000100000000000000".decode('hex'))
#  dbus.ByteArray("020500006b00000000000000000000000800000000000000010000001c000000820000000100000002000000020000000000000001000000240000006b00000002000000010000000100000002000000010000000000000001000000240000003a01000002000000010000000100000002000000010000000000000001000000240000006e01000002000000010000000100000002000000010000000000000001000000240000000e0100000200000001000000010000000200000001000000000000000100000024000000250100000200000001000000010000000200000001000000000000000100000024000000a10100000200000001000000010000000200000001000000000000000100000024000000c7010000020000000100000001000000020000000100000000000000".decode('hex'))
    )
    print "initialized dummy screen, handle:", self.dummy_screen_handle
    
  def force_screen_visible(self):
    assert self.last_active_handle is not None
    print "force_screen_visible"
    genericdisplay.SetActiveHandle(self.dummy_screen_handle, 1)
  
  def hide_screen(self):
    assert self.last_active_handle is not None
    print "hide_screen"
    genericdisplay.SetActiveHandle(self.last_active_handle, 1)

  def destroy(self):
    if self.visible:
      print "currently visible, hiding screen first."
      self.pending_destroy = True
      self.hide_screen()
      return

    if self.dummy_screen_handle:
      print "deleteHandle", self.genericdisplay.DeleteHandle(self.dummy_screen_handle)
      global mainloop
      mainloop.quit()

  def activate(self):
    print "CUSTOM SCREEN ACTIVATED"
    self.update()

  def deactivate(self):
    print "CUSTOM SCREEN DEACTIVATED"

  def ShowScreen(self, screen_lines, screen_number = 2, x4 = 7, scroll_position = 0, num_menu_entries = 4):
    assert self.visible
    result = b("0080") + chr(screen_number) + b("0000") + chr(x4) + b("00") +  chr(len(screen_lines)) + b("0000") + chr(scroll_position) + chr(num_menu_entries) + chr(len(screen_lines))

    for index, (flags, text) in enumerate(screen_lines):
      data = chr(index) + struct.pack("<H", flags) + chr(len(text)) + text
      result += b("3300") + chr(len(data) + 3) + data

    self.s12x.ScreenData(dbus.ByteArray(result))

  def update(self):
    screen_number, lines, scroll_position, num_menu_entries = self.screen_stack[-1].render()
    self.ShowScreen(lines, scroll_position = scroll_position, num_menu_entries = num_menu_entries, screen_number = screen_number)

class MainMenu(Menu):
  HEADER = ["My Custom Menu"]
  MENU_ENTRIES = ["Choice 1", "Choice 2", "Exit"]
  
  def __init__(self):
    Menu.__init__(self, self.HEADER, self.MENU_ENTRIES)
  
  def selected(self, result):
    print "MAIN MENU SELECTED, res=", result
    if result is None or result == 2: # back or exit
      self.closed = True
      self.result = None
    else:
      print "menu menu invoke", result


bap_display = BapDisplay(genericdisplay, s12x, MainMenu())

# by default, BapDisplay waits until it sees an 
# ActiveHandleChangedNotification, so it can switch back to the original
# window. For testing, you can just force this, but it will mess up the
# window stack.

#bap_display.ActiveHandleChangedNotification(dbus.UInt32(2))
mainloop = gobject.MainLoop()
mainloop.run()
