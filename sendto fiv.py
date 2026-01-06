from gpiozero import Button
from signal import pause
import vlc
import time
from vlc import MediaPlayer,MediaList,MediaListPlayer

# Define the GPIO pin connected to the button (e.g., pin 17)
button17 = Button(17) 
button27 = Button(27) 
button22 = Button(22) 
button4 = Button(4) 
# Initialize VLC instance and media player
vlc_instance = vlc.Instance()

list_player: MediaListPlayer = vlc_instance.media_list_player_new()

list_player.set_playback_mode(vlc.PlaybackMode(1))

media_player: MediaPlayer = vlc_instance.media_player_new()

media_player.set_fullscreen(True)

list_player.set_media_player(media_player)


def play_video(path):
   # Create and set the new media list BEFORE stopping
   media_list: MediaList = vlc_instance.media_list_new()
   media_list.add_media(path)
   list_player.set_media_list(media_list)
   
   # Now play (which will stop the current video and start the new one)
   list_player.play()
   print("Video started!")
    
    
def exit_vlc():
    media_player.stop()
    print("Exit vlc")
    
    
    
def button_pressed_17():
    print("Button 17 was pressed!")
    play_video("/home/helmwash/Videos/Process.mp4")

def button_pressed_27():
    print("Button 27 was pressed!")
    play_video("/home/helmwash/Videos/Place.mp4")

def button_pressed_22():
    print("Button 22 was pressed!")
    play_video("/home/helmwash/Videos/Warning.mp4")
	
def button_pressed_4():
    print("Button 4 was pressed!")
    exit_vlc()
 

# Assign functions to be called when the button is pressed or released
button17.when_pressed = button_pressed_17
button27.when_pressed = button_pressed_27
button22.when_pressed = button_pressed_22
button4.when_pressed = button_pressed_4
   

#button.when_released = button_released

print("Waiting for button presses...")
pause() # Keep the script running indefinitely
