def update_topic_weight(current_weight, feedback_type):
    LEARNING_RATE = 0.2
    MIN_WEIGHT = 0.1
    MAX_WEIGHT = 1.0
    
    if feedback_type == "like":
        delta = 0.2
    elif feedback_type == "dislike":
        delta = -0.25
    elif feedback_type == "no_reaction":
        delta = -0.03
    
    new_weight = current_weight + LEARNING_RATE * delta
    return max(MIN_WEIGHT, min(MAX_WEIGHT, new_weight))
