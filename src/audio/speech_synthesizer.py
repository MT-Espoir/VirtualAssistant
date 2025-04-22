import pyttsx3
import threading
import os
from gtts import gTTS
import tempfile
import pygame
import time
import queue

class SpeechSynthesizer:
    """
    Speech synthesizer class for converting text to speech
    Supports both offline (pyttsx3) and online (gTTS) synthesis
    """
    
    def __init__(self, engine="pyttsx3", language="vi", rate=150, volume=1.0):
        """
        Initialize the speech synthesizer
        
        Args:
            engine (str): The TTS engine to use ("pyttsx3" or "gtts")
            language (str): The language code (e.g., "vi" for Vietnamese, "en" for English)
            rate (int): Speech rate for pyttsx3 (higher = faster)
            volume (float): Speech volume (0.0 to 1.0)
        """
        self.engine_type = engine
        self.language = language
        self.rate = rate
        self.volume = volume
        self.voice_queue = queue.Queue()
        self.is_speaking = False
        self.stop_requested = False
        
        # Initialize the appropriate TTS engine
        if self.engine_type == "pyttsx3":
            self.engine = pyttsx3.init()
            self.engine.setProperty('rate', self.rate)
            self.engine.setProperty('volume', self.volume)
            
            # Try to set a voice based on the language
            voices = self.engine.getProperty('voices')
            selected_voice = None
            
            for voice in voices:
                if self.language in voice.id.lower():
                    selected_voice = voice.id
                    break
            
            # If we found a matching voice, set it
            if selected_voice:
                self.engine.setProperty('voice', selected_voice)
                
        # Initialize pygame for gtts playback
        elif self.engine_type == "gtts":
            pygame.mixer.init()
            
        # Start the speaking thread
        self._start_speaking_thread()
    
    def _start_speaking_thread(self):
        """Start a background thread to handle speech synthesis"""
        self.speak_thread = threading.Thread(target=self._process_speech_queue, daemon=True)
        self.speak_thread.start()
    
    def _process_speech_queue(self):
        """Process items in the speech queue"""
        while True:
            if not self.stop_requested:
                try:
                    # Get text from queue with a timeout to allow checking stop_requested
                    text = self.voice_queue.get(timeout=0.5)
                    self.is_speaking = True
                    
                    if self.engine_type == "pyttsx3":
                        self.engine.say(text)
                        self.engine.runAndWait()
                    elif self.engine_type == "gtts":
                        self._speak_with_gtts(text)
                    
                    self.is_speaking = False
                    self.voice_queue.task_done()
                except queue.Empty:
                    # Queue is empty, just continue the loop
                    pass
                except Exception as e:
                    print(f"Error in speech synthesis: {e}")
                    self.is_speaking = False
            else:
                time.sleep(0.1)  # Sleep to reduce CPU usage when stopped
                
    def _speak_with_gtts(self, text):
        """Use Google Text-to-Speech to convert text to speech"""
        try:
            # Create a temporary file for the audio
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_file:
                temp_filename = temp_file.name
            
            # Generate the speech with gTTS
            tts = gTTS(text=text, lang=self.language, slow=False)
            tts.save(temp_filename)
            
            # Play the audio file
            pygame.mixer.music.load(temp_filename)
            pygame.mixer.music.play()
            
            # Wait for the audio to finish playing
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
                
            # Clean up the temporary file after playing
            try:
                os.unlink(temp_filename)
            except:
                pass  # Ignore cleanup errors
                
        except Exception as e:
            print(f"Error in gTTS speech synthesis: {e}")
    
    def speak(self, text):
        """
        Speak the given text using the selected TTS engine
        
        Args:
            text (str): Text to be spoken
        """
        if text and not self.stop_requested:
            self.voice_queue.put(text)
            return True
        return False
    
    def speak_sync(self, text):
        """
        Speak the given text synchronously (blocking until speech finishes)
        
        Args:
            text (str): Text to be spoken
        """
        if not text or self.stop_requested:
            return False
            
        if self.engine_type == "pyttsx3":
            self.is_speaking = True
            self.engine.say(text)
            self.engine.runAndWait()
            self.is_speaking = False
            return True
        elif self.engine_type == "gtts":
            self.is_speaking = True
            self._speak_with_gtts(text)
            self.is_speaking = False
            return True
        
        return False
    
    def stop(self):
        """Stop ongoing speech and clear the queue"""
        self.stop_requested = True
        
        # Clear the queue
        while not self.voice_queue.empty():
            try:
                self.voice_queue.get_nowait()
                self.voice_queue.task_done()
            except queue.Empty:
                break
        
        if self.engine_type == "pyttsx3":
            try:
                self.engine.stop()
            except:
                pass  # Ignore errors when stopping
        elif self.engine_type == "gtts":
            try:
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
            except:
                pass  # Ignore errors when stopping
        
        self.is_speaking = False
        self.stop_requested = False
        
    def change_voice(self, language=None, index=None):
        """
        Change the voice of the speech synthesizer
        
        Args:
            language (str): The language code to switch to
            index (int): Voice index to use (alternative to language)
        """
        if self.engine_type == "pyttsx3":
            voices = self.engine.getProperty('voices')
            
            if index is not None and 0 <= index < len(voices):
                self.engine.setProperty('voice', voices[index].id)
                return True
            
            if language:
                for voice in voices:
                    if language in voice.id.lower():
                        self.engine.setProperty('voice', voice.id)
                        self.language = language
                        return True
            
            return False
        
        elif self.engine_type == "gtts" and language:
            self.language = language
            return True
        
        return False
    
    def adjust_rate(self, rate):
        """
        Adjust the speech rate
        
        Args:
            rate (int): New speech rate (pyttsx3 only)
        """
        if self.engine_type == "pyttsx3":
            self.rate = rate
            self.engine.setProperty('rate', rate)
            return True
        return False
    
    def adjust_volume(self, volume):
        """
        Adjust the speech volume
        
        Args:
            volume (float): New volume level (0.0 to 1.0)
        """
        if volume < 0.0 or volume > 1.0:
            return False
            
        self.volume = volume
        
        if self.engine_type == "pyttsx3":
            self.engine.setProperty('volume', volume)
        elif self.engine_type == "gtts":
            try:
                pygame.mixer.music.set_volume(volume)
            except:
                pass
                
        return True
        
    def get_available_voices(self):
        """Get list of available voices (pyttsx3 only)"""
        if self.engine_type == "pyttsx3":
            voices = self.engine.getProperty('voices')
            voice_list = []
            
            for idx, voice in enumerate(voices):
                voice_info = {
                    'id': voice.id,
                    'name': voice.name,
                    'index': idx
                }
                voice_list.append(voice_info)
                
            return voice_list
            
        return []