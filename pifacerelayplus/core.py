import pifacecommon.interrupts
import pifacecommon.mcp23s17
import time


# /dev/spidev<bus>.<chipselect>
DEFAULT_SPI_BUS = 0
DEFAULT_SPI_CHIP_SELECT = 0


# Datasheet says coast is 0, 0 and bake is 1, 1. I think it's wrong.
# (pin_num1, pin_num2)
MOTOR_DC_COAST_BITS = (1, 1)  # Z, Z
MOTOR_DC_REVERSE_BITS = (0, 1)  # L, H
MOTOR_DC_FORWARD_BITS = (1, 0)  # H, L
MOTOR_DC_BRAKE_BITS = (0, 0)  # L, L

# Plus boards
# Motor board IC datasheet: http://www.ti.com/lit/ds/symlink/drv8835.pdf
RELAY, MOTOR_DC, MOTOR_STEPPER, DIGITAL = range(4)


class NoPiFaceRelayPlusDetectedError(Exception):
    pass


class MotorDC(object):
    """A motor driver attached to a PiFace Relay Plus. Uses DRV8835."""

    def __init__(self, pin1, pin2):
        self.pin1 = pin1
        self.pin2 = pin2
        self.brake()

    def coast(self):
        """Sets the motor so that it is coasting."""
        self.pin1.value = MOTOR_DC_COAST_BITS[0]
        self.pin2.value = MOTOR_DC_COAST_BITS[1]

    def reverse(self):
        """Sets the motor so that it is moving in reverse."""
        self.pin1.value = MOTOR_DC_REVERSE_BITS[0]
        self.pin2.value = MOTOR_DC_REVERSE_BITS[1]

    def forward(self):
        """Sets the motor so that it is moving forward."""
        self.pin1.value = MOTOR_DC_FORWARD_BITS[0]
        self.pin2.value = MOTOR_DC_FORWARD_BITS[1]

    def brake(self):
        """Stop the motor."""
        self.pin1.value = MOTOR_DC_BRAKE_BITS[0]
        self.pin2.value = MOTOR_DC_BRAKE_BITS[1]


class MotorStepper(object):
    """A stepper motor driver attached to a PiFace Relay Plus. Uses DRV8835."""

    step_states = (0xa, 0x2, 0x6, 0x4, 0x5, 0x1, 0x9, 0x8)

    def __init__(self, index, chip):
        self.chip = chip
        if index == 0:
            self.set_stepper = self._set_stepper0
        else:
            self.set_stepper = self._set_stepper1

    def _set_stepper0(self, value):
        """GPIOB lower nibble, polarity reversed."""
        gpiob = self.chip.gpiob.value & 0xf0
        self.chip.gpiob.value = gpiob | ((value & 0xf) ^ 0xf)

    def _set_stepper1(self, value):
        """GPIOA upper nibble, normal polarity."""
        gpioa = self.chip.gpioa.value & 0x0f
        self.chip.gpioa.value = gpioa | ((value & 0xf) << 4)

    def _send_steps(self, step_states, steps, step_delay):
        for i in range(steps):
            step_index = i % len(step_states)
            self.set_stepper(step_states[step_index])
            time.sleep(step_delay)

    def coast(self):
        """Sets the motor so that it is coasting."""
        self.set_stepper(0x0)

    def reverse(self, steps, step_delay):
        """Sets the motor so that it is moving in reverse."""
        self._send_steps(reversed(self.step_states), steps, step_delay)

    def forward(self, steps, step_delay):
        """Sets the motor so that it is moving forward."""
        self._send_steps(self.step_states, steps, step_delay)

    def brake(self):
        """Stop the motor."""
        self.set_stepper(0xf)


class PiFaceRelayPlus(pifacecommon.mcp23s17.MCP23S17,
                      pifacecommon.interrupts.GPIOInterruptDevice):
    """A PiFace Relay Plus board.

    Example:

    >>> pfrp = pifacerelayplus.PiFaceRelayPlus(pifacerelayplus.MOTOR)
    >>> pfrp.inputs[2].value
    0
    >>> pfrp.relays[3].turn_on()
    >>> pfrp.motor[2].forward()
    """

    def __init__(self,
                 plus_board,
                 hardware_addr=0,
                 bus=DEFAULT_SPI_BUS,
                 chip_select=DEFAULT_SPI_CHIP_SELECT,
                 init_board=True):
        super(PiFaceRelayPlus, self).__init__(hardware_addr, bus, chip_select)

        pcmcp = pifacecommon.mcp23s17

        # input_pins are always the upper nibble of GPIOB
        self.input_pins = [pcmcp.MCP23S17RegisterBitNeg(i,
                                                        pcmcp.GPIOB,
                                                        self)
                           for i in range(8)]
        self.input_port = pcmcp.MCP23S17RegisterNibbleNeg(pcmcp.UPPER_NIBBLE,
                                                          pcmcp.GPIOB,
                                                          self)

        self.relay_port = pcmcp.MCP23S17Register(pcmcp.GPIOA, self)

        # Relays are always lower nibble of GPIOA, order is reversed
        self.relays = list(reversed([pcmcp.MCP23S17RegisterBit(i,
                                                               pcmcp.GPIOA,
                                                               self)
                                     for i in range(0, 4)]))

        if plus_board == RELAY:
            # append 4 relays
            self.relays.extend([pcmcp.MCP23S17RegisterBit(i, pcmcp.GPIOA, self)
                                for i in range(4, 8)])

        elif plus_board == MOTOR_DC:
            self.motors = [
                MotorDC(
                    pin1=pcmcp.MCP23S17RegisterBitNeg(3, pcmcp.GPIOB, self),
                    pin2=pcmcp.MCP23S17RegisterBitNeg(2, pcmcp.GPIOB, self)),
                MotorDC(
                    pin1=pcmcp.MCP23S17RegisterBitNeg(1, pcmcp.GPIOB, self),
                    pin2=pcmcp.MCP23S17RegisterBitNeg(0, pcmcp.GPIOB, self)),
                MotorDC(pin1=pcmcp.MCP23S17RegisterBit(4, pcmcp.GPIOA, self),
                        pin2=pcmcp.MCP23S17RegisterBit(5, pcmcp.GPIOA, self)),
                MotorDC(pin1=pcmcp.MCP23S17RegisterBit(6, pcmcp.GPIOA, self),
                        pin2=pcmcp.MCP23S17RegisterBit(7, pcmcp.GPIOA, self)),
            ]

        elif plus_board == MOTOR_STEPPER:
            self.motors = [MotorStepper(i, self) for i in range(2)]

        elif plus_board == DIGITAL:
            pass

        if init_board:
            self.init_board()

    def __del__(self):
        self.disable_interrupts()
        super(PiFaceRelayPlus, self).__del__()

    def enable_interrupts(self):
        self.gpintenb.value = 0xF0
        self.gpio_interrupts_enable()

    def disable_interrupts(self):
        self.gpintenb.value = 0x00
        self.gpio_interrupts_disable()

    def init_board(self):
        ioconfig = (pifacecommon.mcp23s17.BANK_OFF |
                    pifacecommon.mcp23s17.INT_MIRROR_OFF |
                    pifacecommon.mcp23s17.SEQOP_OFF |
                    pifacecommon.mcp23s17.DISSLW_OFF |
                    pifacecommon.mcp23s17.HAEN_ON |
                    pifacecommon.mcp23s17.ODR_OFF |
                    pifacecommon.mcp23s17.INTPOL_LOW)
        self.iocon.value = ioconfig
        if self.iocon.value != ioconfig:
            raise NoPiFaceRelayPlusDetectedError(
                "No PiFace Relay Plus board detected (hardware_addr={h}, "
                "bus={b}, chip_select={c}).".format(
                    h=self.hardware_addr, b=self.bus, c=self.chip_select))
        else:
            # finish configuring the board
            self.gpioa.value = 0
            self.iodira.value = 0  # GPIOA as outputs
            self.iodirb.value = 0xf0  # GPIOB lower nibble as outputs
            self.gppub.value = 0xf0
            self.enable_interrupts()


class InputEventListener(pifacecommon.interrupts.PortEventListener):
    """Listens for events on the input port and calls the mapped callback
    functions.

    >>> def print_flag(event):
    ...     print(event.interrupt_flag)
    ...
    >>> listener = pifacerelayplus.InputEventListener()
    >>> listener.register(0, pifacerelayplus.IODIR_ON, print_flag)
    >>> listener.activate()
    """
    def __init__(self, chip):
        super(InputEventListener, self).__init__(
            pifacecommon.mcp23s17.GPIOB, chip)
