#ifndef ___NODE__H___
#define ___NODE__H___

#include <stdint.h>
#include <EEPROM.h>
#include <remote_i2c_command.h>
#include "Memory.h"
#include "Array.h"
#include "RPCBuffer.h"
#define BROADCAST_ADDRESS 0x00


/* Callback functions for slave device. */
extern void i2c_receive_event(int byte_count);
extern void i2c_request_event();


class Node {
public:
  static const uint16_t EEPROM__I2C_ADDRESS = 0x00;
  uint8_t i2c_address_;
  uint8_t output_buffer[20];
  i2c_query i2c_query_;

  Node() {
    UInt8Array i2c_array = {sizeof(output_buffer), output_buffer};
    i2c_query_ = i2c_query(i2c_array);
    i2c_address_ = EEPROM.read(EEPROM__I2C_ADDRESS);
    Wire.begin(i2c_address_);
  }

  uint32_t microseconds() { return micros(); }
  uint32_t milliseconds() { return millis(); }
  void delay_us(uint16_t us) { if (us > 0) { delayMicroseconds(us); } }
  void delay_ms(uint16_t ms) { if (ms > 0) { delay(ms); } }
  uint32_t max_payload_size() {
    return (PACKET_SIZE
            - 3 * sizeof(uint8_t)  // Frame boundary
            - sizeof(uint16_t)  // UUID
            - sizeof(uint16_t));  // Payload length
  }
  uint32_t ram_free() { return free_memory(); }
  void pin_mode(uint8_t pin, uint8_t mode) { return pinMode(pin, mode); }
  uint8_t digital_read(uint8_t pin) const { return digitalRead(pin); }
  void digital_write(uint8_t pin, uint8_t value) { digitalWrite(pin, value); }
  uint16_t analog_read(uint8_t pin) const { return analogRead(pin); }
  void analog_write(uint8_t pin, uint8_t value) { return analogWrite(pin, value); }
  int i2c_address() const { return i2c_address_; }
  int set_i2c_address(uint8_t address) {
    i2c_address_ = address;
    Wire.begin(address);
    // Write the value to the appropriate byte of the EEPROM.
    // These values will remain there when the board is turned off.
    EEPROM.write(EEPROM__I2C_ADDRESS, i2c_address_);
    return address;
  }

  uint16_t array_length(UInt8Array array) { return array.length; }
  UInt32Array echo_array(UInt32Array array) { return array; }

  UInt8Array str_demo() {
    /* # `str_demo` #
     *
     * This method demonstrates how to return a string of characters stored in
     * program memory as an array of bytes.
     *
     * ## Example Python code ##
     *
     *     >>> import numpy as np
     *     >>> from arduino_rpc.board import ArduinoRPCBoard
     *     >>> b = ArduinoRPCBoard('/dev/ttyUSB1')
     *
     *     free memory: 270
     *     >>> np.array(b.str_demo(), dtype=np.uint8).tostring()
     *     'hello'
     */
    UInt8Array result;
    result.data = reinterpret_cast<uint8_t *>(&output_buffer[0]);
    strcpy_P(reinterpret_cast<char *>(result.data), PSTR("hello"));
    result.length = 5;
    return result;
  }

  UInt8Array str_echo(UInt8Array msg) { return msg; }

  uint32_t get_millis() { return millis(); }
};


#endif  // #ifndef ___NODE__H___