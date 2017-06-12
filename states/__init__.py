# class StateMachine(object):
#     def __init__(self, initial_state):
#         self.current_state = initial_state
#         self.current_state.run()
#
#     def run_all(self, inputs):
#         for i in inputs:
#             print(i)
#             self.current_state = self.current_state.next(i)
#             self.current_state.run()


class State(object):
    def run(self, payload):
        # logger.info('State %s run', self.__class__.__name__)
        assert 0, "run not implemented"

    def nex(self, payload):
        # logger.info('State %s nex', self.__class__.__name__)
        assert 0, "next not implemented"
