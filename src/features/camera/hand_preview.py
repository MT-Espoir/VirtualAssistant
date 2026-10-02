"""Draw transient MediaPipe hand joints on a debug-only webcam frame."""

import math


FINGER_CHAINS = (
    ((0, 1, 2, 3, 4), (80, 185, 255)),   # thumb: orange
    ((0, 5, 6, 7, 8), (255, 170, 70)),   # index: blue
    ((0, 9, 10, 11, 12), (80, 225, 120)),  # middle: green
    ((0, 13, 14, 15, 16), (205, 100, 245)),  # ring: purple
    ((0, 17, 18, 19, 20), (105, 245, 245)),  # pinky: yellow
)
PALM = ((5, 9), (9, 13), (13, 17), (17, 0))


def draw_hand_skeleton(frame, hands, cv2):
    """Mutate only the private preview copy; never retain image or landmarks."""
    height, width = frame.shape[:2]
    for hand in hands:
        if len(hand) != 21 or any(
                not math.isfinite(x) or not math.isfinite(y) for x, y in hand):
            continue
        points = tuple((round(x * (width - 1)), round(y * (height - 1)))
                       for x, y in hand)
        for start, end in PALM:
            cv2.line(frame, points[start], points[end], (210, 210, 210), 2)
        for chain, color in FINGER_CHAINS:
            for start, end in zip(chain, chain[1:]):
                cv2.line(frame, points[start], points[end], color, 2)
            for joint in chain[1:]:
                cv2.circle(frame, points[joint], 3 if joint != chain[-1] else 5,
                           color, -1)
        cv2.circle(frame, points[0], 4, (255, 255, 255), -1)
    return frame
