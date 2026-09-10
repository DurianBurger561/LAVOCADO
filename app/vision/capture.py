"""
 capture the screen shot
"""

import mss
import numpy
from PIL import Image
from app import config



class Capturer:

  def __init__(self):
     self.cut = mss.mss()


  def grab(self):
     monitor = self.cut.monitors[1] # choose the main display
     screenshot = self.cut.grab(monitor) # store the screenshot

     img = Image.fromarray( # transfer from BGRA to PIL's RGB
        "RGB",
        screenshot.size,
        screenshot.bgra,
        "raw",
        "BGRX",
     )
     img.thumbnail((config.THUMBNAIL_SIZE, config.THUMBNAIL_SIZE))
     return numpy.array(img)