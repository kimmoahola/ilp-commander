import random
import math
import time

from poller_helpers import Commands, logger

seed = int(time.time())
random.seed(seed)

# Shorthand:
#   "pd_" as a variable prefix means "partial derivative"
#   "d_" as a variable prefix means "derivative"
#   "_wrt_" is shorthand for "with respect to"
#   "w_ho" and "w_ih" are the index of weights from hidden to output layer neurons and input to hidden layer neurons respectively
#
# Comment references:
#
# [1] Wikipedia article on Backpropagation
#   http://en.wikipedia.org/wiki/Backpropagation#Finding_the_derivative_of_the_error
# [2] Neural Networks for Machine Learning course on Coursera by Geoffrey Hinton
#   https://class.coursera.org/neuralnets-2012-001/lecture/39
# [3] The Back Propagation Algorithm
#   https://www4.rgu.ac.uk/files/chapter3%20-%20bp.pdf


class NeuralNetwork:
    LEARNING_RATE = 0.5

    def __init__(self, num_inputs, num_hidden, num_outputs, hidden_layer_weights=None, hidden_layer_bias=None,
                 output_layer_weights=None, output_layer_bias=None):
        self.num_inputs = num_inputs

        self.hidden_layer = NeuronLayer(num_hidden, hidden_layer_bias)
        self.output_layer = NeuronLayer(num_outputs, output_layer_bias)

        self.init_weights_from_inputs_to_hidden_layer_neurons(hidden_layer_weights)
        self.init_weights_from_hidden_layer_neurons_to_output_layer_neurons(output_layer_weights)

    def init_weights_from_inputs_to_hidden_layer_neurons(self, hidden_layer_weights):
        weight_num = 0
        for h in range(len(self.hidden_layer.neurons)):
            for i in range(self.num_inputs):
                if not hidden_layer_weights:
                    self.hidden_layer.neurons[h].weights.append(random.random())
                else:
                    self.hidden_layer.neurons[h].weights.append(hidden_layer_weights[weight_num])
                weight_num += 1

    def init_weights_from_hidden_layer_neurons_to_output_layer_neurons(self, output_layer_weights):
        weight_num = 0
        for o in range(len(self.output_layer.neurons)):
            for h in range(len(self.hidden_layer.neurons)):
                if not output_layer_weights:
                    self.output_layer.neurons[o].weights.append(random.random())
                else:
                    self.output_layer.neurons[o].weights.append(output_layer_weights[weight_num])
                weight_num += 1

    def inspect(self):
        logger.info('------')
        logger.info('* Inputs: {}'.format(self.num_inputs))
        logger.info('------')
        logger.info('Hidden Layer')
        self.hidden_layer.inspect()
        logger.info('------')
        logger.info('* Output Layer')
        self.output_layer.inspect()
        logger.info('------')

    def feed_forward(self, inputs):
        hidden_layer_outputs = self.hidden_layer.feed_forward(inputs)
        return self.output_layer.feed_forward(hidden_layer_outputs)

    # Uses online learning, ie updating the weights after each training case
    def train(self, training_inputs, training_outputs):
        self.feed_forward(training_inputs)

        # 1. Output neuron deltas
        pd_errors_wrt_output_neuron_total_net_input = [0] * len(self.output_layer.neurons)
        for o in range(len(self.output_layer.neurons)):
            # ∂E/∂zⱼ
            pd_errors_wrt_output_neuron_total_net_input[o] = self.output_layer.neurons[
                o].calculate_pd_error_wrt_total_net_input(training_outputs[o])

        # 2. Hidden neuron deltas
        pd_errors_wrt_hidden_neuron_total_net_input = [0] * len(self.hidden_layer.neurons)
        for h in range(len(self.hidden_layer.neurons)):

            # We need to calculate the derivative of the error with respect to the output of each hidden layer neuron
            # dE/dyⱼ = Σ ∂E/∂zⱼ * ∂z/∂yⱼ = Σ ∂E/∂zⱼ * wᵢⱼ
            d_error_wrt_hidden_neuron_output = 0
            for o in range(len(self.output_layer.neurons)):
                d_error_wrt_hidden_neuron_output += pd_errors_wrt_output_neuron_total_net_input[o] * \
                                                    self.output_layer.neurons[o].weights[h]

            # ∂E/∂zⱼ = dE/dyⱼ * ∂zⱼ/∂
            pd_errors_wrt_hidden_neuron_total_net_input[h] = d_error_wrt_hidden_neuron_output * \
                self.hidden_layer.neurons[h].calculate_pd_total_net_input_wrt_input()

        # 3. Update output neuron weights
        for o in range(len(self.output_layer.neurons)):
            for w_ho in range(len(self.output_layer.neurons[o].weights)):
                # ∂Eⱼ/∂wᵢⱼ = ∂E/∂zⱼ * ∂zⱼ/∂wᵢⱼ
                pd_error_wrt_weight = pd_errors_wrt_output_neuron_total_net_input[o] * self.output_layer.neurons[
                    o].calculate_pd_total_net_input_wrt_weight(w_ho)

                # Δw = α * ∂Eⱼ/∂wᵢ
                self.output_layer.neurons[o].weights[w_ho] -= self.LEARNING_RATE * pd_error_wrt_weight

        # 4. Update hidden neuron weights
        for h in range(len(self.hidden_layer.neurons)):
            for w_ih in range(len(self.hidden_layer.neurons[h].weights)):
                # ∂Eⱼ/∂wᵢ = ∂E/∂zⱼ * ∂zⱼ/∂wᵢ
                pd_error_wrt_weight = pd_errors_wrt_hidden_neuron_total_net_input[h] * self.hidden_layer.neurons[
                    h].calculate_pd_total_net_input_wrt_weight(w_ih)

                # Δw = α * ∂Eⱼ/∂wᵢ
                self.hidden_layer.neurons[h].weights[w_ih] -= self.LEARNING_RATE * pd_error_wrt_weight

        # 5. Update output neuron bias
        for o in range(len(self.output_layer.neurons)):
            # ∂Eⱼ/∂wᵢⱼ = ∂E/∂zⱼ * ∂zⱼ/∂wᵢⱼ
            pd_error_wrt_weight = pd_errors_wrt_output_neuron_total_net_input[o] * \
                                  self.output_layer.neurons[o].calculate_pd_total_net_input_bias()

            # Δw = α * ∂Eⱼ/∂wᵢ
            self.output_layer.neurons[o].bias -= self.LEARNING_RATE * pd_error_wrt_weight

            # 6. Update hidden neuron weights
        for h in range(len(self.hidden_layer.neurons)):
            # ∂Eⱼ/∂wᵢ = ∂E/∂zⱼ * ∂zⱼ/∂wᵢ
            pd_error_wrt_weight = pd_errors_wrt_hidden_neuron_total_net_input[h] * \
                                  self.hidden_layer.neurons[h].calculate_pd_total_net_input_bias()

            # Δw = α * ∂Eⱼ/∂wᵢ
            self.hidden_layer.neurons[h].bias -= self.LEARNING_RATE * pd_error_wrt_weight

    def calculate_total_error(self, training_sets):
        total_error = 0
        for t in range(len(training_sets)):
            training_inputs, training_outputs = training_sets[t]
            self.feed_forward(training_inputs)
            for o in range(len(training_outputs)):
                total_error += self.output_layer.neurons[o].calculate_error(training_outputs[o])
        return total_error

    def predict(self, inp):
        self.feed_forward(inp)
        output_array = [n.output for n in self.output_layer.neurons]
        return output_array


class NeuronLayer:
    def __init__(self, num_neurons, bias):

        # Every neuron in a layer shares the same bias
        self.bias = bias if bias else random.random()

        self.neurons = []
        for i in range(num_neurons):
            self.neurons.append(Neuron(self.bias))

    # one bias value per neuron
    def inspect(self):
        logger.info('Neurons: {}'.format(len(self.neurons)))
        for n in range(len(self.neurons)):
            logger.info(' Neuron {}'.format(n))
            for w in range(len(self.neurons[n].weights)):
                logger.info('  Weight: {}'.format(self.neurons[n].weights[w]))
            logger.info('  Bias: {}'.format(self.neurons[0].bias))

    def feed_forward(self, inputs):
        outputs = []
        for neuron in self.neurons:
            neuron.set_inputs(inputs)
            outputs.append(neuron.calculate_output())
        return outputs

    def get_outputs(self):
        outputs = []
        for neuron in self.neurons:
            outputs.append(neuron.output)
        return outputs


class Neuron:
    def __init__(self, bias):
        self.inputs = []
        self.output = 0
        self.bias = bias
        self.weights = []

    def set_inputs(self, inputs):
        self.inputs = inputs

    def calculate_output(self):
        self.output = self.squash(self.calculate_total_net_input(self.inputs))
        return self.output

    def calculate_total_net_input(self, inputs):
        total = 0
        for i in range(len(inputs)):
            total += inputs[i] * self.weights[i]
        return total + self.bias

    # Apply the logistic function to squash the output of the neuron
    # The result is sometimes referred to as 'net' [2] or 'net' [1]
    @staticmethod
    def squash(total_net_input):
        return 1 / (1 + math.exp(-total_net_input))

    # Determine how much the neuron's total input has to change to move closer to the expected output
    #
    # Now that we have the partial derivative of the error with respect to the output (∂E/∂yⱼ) and
    # the derivative of the output with respect to the total net input (dyⱼ/dzⱼ) we can calculate
    # the partial derivative of the error with respect to the total net input.
    # This value is also known as the delta (δ) [1]
    # δ = ∂E/∂zⱼ = ∂E/∂yⱼ * dyⱼ/dzⱼ
    #
    def calculate_pd_error_wrt_total_net_input(self, target_output):
        return self.calculate_pd_error_wrt_output(target_output) * self.calculate_pd_total_net_input_wrt_input()

    # The error for each neuron is calculated by the Mean Square Error method:
    def calculate_error(self, target_output):
        return 0.5 * (target_output - self.output) ** 2

    # The partial derivate of the error with respect to actual output then is calculated by:
    # = 2 * 0.5 * (target output - actual output) ^ (2 - 1) * -1
    # = -(target output - actual output)
    #
    # The Wikipedia article on backpropagation [1] simplifies to the following, but most other learning material does not [2]
    # = actual output - target output
    #
    # Alternative, you can use (target - output), but then need to add it during backpropagation [3]
    #
    # Note that the actual output of the output neuron is often written as yⱼ and target output as tⱼ so:
    # = ∂E/∂yⱼ = -(tⱼ - yⱼ)
    def calculate_pd_error_wrt_output(self, target_output):
        return -(target_output - self.output)

    # The total net input into the neuron is squashed using logistic function to calculate the neuron's output:
    # yⱼ = φ = 1 / (1 + e^(-zⱼ))
    # Note that where ⱼ represents the output of the neurons in whatever layer we're looking at and ᵢ represents the layer below it
    #
    # The derivative (not partial derivative since there is only one variable) of the output then is:
    # dyⱼ/dzⱼ = yⱼ * (1 - yⱼ)
    def calculate_pd_total_net_input_wrt_input(self):
        return self.output * (1 - self.output)

    # The total net input is the weighted sum of all the inputs to the neuron and their respective weights:
    # = zⱼ = netⱼ = x₁w₁ + x₂w₂ ... + b
    #
    # The partial derivative of the total net input with respective to a given weight (with everything else held constant) then is:
    # = ∂zⱼ/∂wᵢ = some constant + 1 * xᵢw₁^(1-0) + some constant ... = xᵢ
    def calculate_pd_total_net_input_wrt_weight(self, index):
        return self.inputs[index]

    @staticmethod
    def calculate_pd_total_net_input_bias():
        return 1


def filter_training_sets(training_sets):
    same_tolerances = [1, 0.2, 0.2, 3]

    new_training_sets = []

    for index, training_set in enumerate(training_sets):
        inputs, outputs = training_set
        for training_set_to_compare in training_sets[index+1:]:
            compare_inputs = training_set_to_compare[0]
            diff = map(
                lambda x: x[0] <= x[1],
                zip(map(lambda x: abs(x[0]-x[1]), zip(inputs, compare_inputs)), same_tolerances))
            if all(diff):
                break
        else:
            new_training_sets.append(training_set)

    logger.info('dropped {}'.format(len(training_sets) - len(new_training_sets)))
    return new_training_sets


def train(training_sets):

    filtered_training_sets = filter_training_sets(training_sets)

    hidden_networks_to_try = range(8, 21, 3)

    nn = None

    for num_hidden in hidden_networks_to_try:

        logger.info('try {} hidden'.format(num_hidden))

        nn = NeuralNetwork(len(filtered_training_sets[0][0]), num_hidden, len(filtered_training_sets[0][1]))
        for i in range(100000):
            if i % 10000 == 9999:
                this_error = nn.calculate_total_error(filtered_training_sets)
                logger.info(str(this_error))
                if this_error < 0.01:
                    logger.info('training iterations {}'.format(i))
                    return nn
            training_inputs, training_outputs = random.choice(filtered_training_sets)
            nn.train(training_inputs, training_outputs)

    total_error = nn.calculate_total_error(filtered_training_sets)
    logger.info('total error {} {}'.format(total_error, '!!!!!!!' if total_error > 0.01 else 'ok'))

    return nn


def predict(nn, inp):
    output_groups = [Commands.off, Commands.heat8, Commands.heat10, Commands.heat16, Commands.heat22]
    predicted = nn.predict(inp)
    predicted_mode = output_groups[predicted.index(max(predicted))]
    logger.info('predicted {} -> {} ({})'.format(inp, predicted_mode, max(predicted)))
    return predicted_mode