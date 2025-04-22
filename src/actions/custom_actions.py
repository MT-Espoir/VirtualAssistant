class CustomActions:
    def __init__(self):
        pass

    def perform_action(self, action_name, *args, **kwargs):
        if action_name == "custom_action_1":
            return self.custom_action_1(*args, **kwargs)
        elif action_name == "custom_action_2":
            return self.custom_action_2(*args, **kwargs)
        else:
            raise ValueError(f"Action '{action_name}' is not recognized.")

    def custom_action_1(self, param1):
        # Implement the logic for custom action 1
        print(f"Performing custom action 1 with parameter: {param1}")

    def custom_action_2(self, param1, param2):
        # Implement the logic for custom action 2
        print(f"Performing custom action 2 with parameters: {param1}, {param2}")