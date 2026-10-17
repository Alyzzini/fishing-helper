"""Lead a moving dot slightly to reduce overshoot, with hysteresis."""
import math


class Tracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = None
        self.velocity = 0.0

    def decide(self, target, dot, now, tolerance, hold_moves_up, held, height):
        error = dot-target
        if self.previous:
            previous_time,previous_error = self.previous
            dt = now-previous_time
            if .002 < dt < .15:
                speed = max(-height*3,min(height*3,(error-previous_error)/dt))
                alpha = 1-math.exp(-dt/.045)
                self.velocity += alpha*(speed-self.velocity)
            else:
                self.velocity = 0.0
        self.previous = now,error
        lead = max(-height*.06,min(height*.06,self.velocity*.045))
        predicted_error = error+lead
        if abs(predicted_error) > tolerance:
            return (predicted_error > 0) == hold_moves_up
        return held
