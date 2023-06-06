"""Control + Betaflight debugging. 

Example
-------
In one terminal build and run SITL Betaflight:

    $ make TARGET=SITL
    $ betaflight/obj/main/betaflight_SITL.elf

In a separate  terminal, run:

    $ python beta.py

Note
---
Comment out line `delayMicroseconds_real(50); // max rate 20kHz` from Betaflight's SIMULATOR_BUILD
https://github.com/betaflight/betaflight/blob/c41b458e5891205da50465caeec0c1aa83beeb0c/src/main/main.c#L52

"""
import os
import time
import argparse
from datetime import datetime
import socket
import struct
import pdb
import math
import random
import numpy as np
import pybullet as p
import matplotlib.pyplot as plt

from gym_pybullet_drones.utils.enums import DroneModel, Physics
from gym_pybullet_drones.envs.CtrlAviary import CtrlAviary
from gym_pybullet_drones.utils.Logger import Logger
from gym_pybullet_drones.utils.utils import sync, str2bool
from transforms3d.quaternions import rotate_vector

DEFAULT_DRONES = DroneModel("racer")
DEFAULT_PHYSICS = Physics("pyb")
DEFAULT_GUI = True
DEFAULT_PLOT = True
DEFAULT_USER_DEBUG_GUI = False
DEFAULT_AGGREGATE = True
DEFAULT_SIMULATION_FREQ_HZ = 500
DEFAULT_CONTROL_FREQ_HZ = 500
DEFAULT_DURATION_SEC = 8.
DEFAULT_OUTPUT_FOLDER = 'results'

UDP_IP = "127.0.0.1"

sock = socket.socket(socket.AF_INET,    # Internet
                     socket.SOCK_DGRAM) # UDP

sock_pwm = socket.socket(socket.AF_INET, # Internet
                     socket.SOCK_DGRAM)  # UDP
sock_pwm.bind((UDP_IP, 9002))
sock_pwm.settimeout(0.0)

# sock_raw = socket.socket(socket.AF_INET, # Internet
#                      socket.SOCK_DGRAM)  # UDP
# sock_raw.bind((UDP_IP, 9001))
# sock_raw.settimeout(0.0)


def run(
        drone=DEFAULT_DRONES,
        physics=DEFAULT_PHYSICS,
        gui=DEFAULT_GUI,
        plot=DEFAULT_PLOT,
        user_debug_gui=DEFAULT_USER_DEBUG_GUI,
        aggregate=DEFAULT_AGGREGATE,
        simulation_freq_hz=DEFAULT_SIMULATION_FREQ_HZ,
        control_freq_hz=DEFAULT_CONTROL_FREQ_HZ,
        duration_sec=DEFAULT_DURATION_SEC,
        output_folder=DEFAULT_OUTPUT_FOLDER,
        ):
    #### Initialize the simulation #############################
    AGGR_PHY_STEPS = int(simulation_freq_hz/control_freq_hz) if aggregate else 1

    #### Create the environment with or without video capture ##
    env = CtrlAviary(drone_model=drone,
                        num_drones=1,
                        initial_xyzs=np.array([[.0, .0, .1]]),
                        initial_rpys=np.array([[.0, .0, .0]]),
                        physics=physics,
                        freq=simulation_freq_hz,
                        aggregate_phy_steps=AGGR_PHY_STEPS,
                        gui=gui,
                        user_debug_gui=user_debug_gui
                        )

    #### Obtain the PyBullet Client ID from the environment ####
    PYB_CLIENT = env.getPyBulletClient()

    #### Initialize the logger #################################
    logger = Logger(logging_freq_hz=int(simulation_freq_hz/AGGR_PHY_STEPS),
                    num_drones=1,
                    output_folder=output_folder,
                    )

    #### Run the simulation ####################################
    CTRL_EVERY_N_STEPS = int(np.floor(env.SIM_FREQ/control_freq_hz))
    action = {'0': np.array([0,0,0,0])}
    previous_vel = np.array([0.,0.,0.])

    START = time.time()
    ARM_TIME = 1.
    for i in range(0, int(duration_sec*env.SIM_FREQ), AGGR_PHY_STEPS):

        #### No gravity until 1.5'' after arming ###################
        # if i/env.SIM_FREQ <= ARM_TIME + 1.5:
        #     p.applyExternalForce(env.DRONE_IDS[0],
        #                          4,
        #                          forceObj=[0, 0, env.GRAVITY],
        #                          posObj=[0, 0, 0],
        #                          flags=p.LINK_FRAME,
        #                          physicsClientId=PYB_CLIENT
        #                          )

        #### Step the simulation ###################################
        obs, reward, terminated, truncated, info = env.step(action)

        #### State message to Betaflight ###########################
        o = obs['0']['state']
        q = np.array([o[6], o[3], o[4], o[5]]) # w, x, y, z
        v = np.array(o[10:13]) # world frame
        v = rotate_vector(v, q) # local frame
        a = (v - previous_vel) * env.SIM_FREQ # local frame
        previous_vel = v # local frame
        w = np.array([o[13:16]]) # world frame
        w = rotate_vector(w, q) # local frame
        # lin_acc = (np.array([o[10], -o[11], -o[12]]) - previous_vel) * env.SIM_FREQ
        # previous_vel = np.array([o[10], -o[11], -o[12]])
        # invDronePos, invDroneOrn = p.invertTransform(o[0:3], o[3:7])
        # rel_lin_acc, _  = p.multiplyTransforms(invDronePos, invDroneOrn, lin_acc, [0.,0.,0.,1.])
        # ang_vel = np.array([o[13], o[14], o[15]])
        # rel_ang_vel = ang_vel # TODO: convert to drone frame
        fdm_packet = struct.pack('@dddddddddddddddddd', 
                            i/env.SIM_FREQ,         # datetime.now().timestamp(), # double timestamp; // in seconds
                            # w[0], w[1], -w[2], # double imu_angular_velocity_rpy[3]; // rad/s -> range: +/- 8192; +/- 2000 deg/se
                            0, 0, -w[2], # double imu_angular_velocity_rpy[3]; // rad/s -> range: +/- 8192; +/- 2000 deg/se
                            # a[0], a[1], a[2], # double imu_linear_acceleration_xyz[3]; // m/s/s NED, body frame -> sim 1G = 9.80665, FC 1G = 256
                            0, 0, 0, # double imu_linear_acceleration_xyz[3]; // m/s/s NED, body frame -> sim 1G = 9.80665, FC 1G = 256
                            # q[0], q[1], q[2], -q[3], # double imu_orientation_quat[4];     // w, x, y, z
                            1, 0, 0, 0, # double imu_orientation_quat[4];     // w, x, y, z
                            # v[0], v[1], v[2],  # double velocity_xyz[3];             // m/s, earth frame
                            0, 0, 0,  # double velocity_xyz[3];             // m/s, earth frame
                            # o[0], o[1], o[2],     # double position_xyz[3];             // meters, NED from origin
                            0, 0, 0,     # double position_xyz[3];             // meters, NED from origin
                            # 101325.0                  # double pressure;
                            1.0                  # double pressure;
                            )
        # print("fdm", struct.unpack('@dddddddddddddddddd', fdm_packet))
        # print("time: {}".format(i/env.SIM_FREQ))
        # print("omega: {}, {}, {}".format(w[0], -w[1], -w[2]))
        # print("acc: {}, {}, {}".format(a[0], -a[1], -a[2]))
        # print("ori: {}, {}, {}, {}".format(q[0], q[1], -q[2], -q[3]))
        # print("vel: {}, {}, {}".format(v[0], -v[1], -v[2]))
        # print("pos: {}, {}, {}".format(o[0], -o[1], -o[2]))
        print("t:[{:.2f}],w:[{:.2f},{:.2f},{:.2f}],a:[{:.2f},{:.2f},{:.2f}],q:[{:.2f},{:.2f},{:.2f},{:.2f}],v:[{:.2f},{:.2f},{:.2f}],p:[{:.2f},{:.2f},{:.2f}]".format(
            i/env.SIM_FREQ, w[0], -w[1], -w[2], a[0], -a[1], -a[2], q[0], q[1], -q[2], -q[3], v[0], -v[1], -v[2], o[0], -o[1], -o[2]))
        sock.sendto(fdm_packet, (UDP_IP, 9003))

        #### RC defaults to Betaflight #############################
        thro = 1000 # Positive up
        yaw = 1500 # Positive CCW
        pitch = 1500 # Positive forward in x
        roll = 1500 # Positive right/forward in y

        #### Ctrl sandbox ##########################################
        # if i/env.SIM_FREQ >= ARM_TIME+1.5: # No gravity even after arming
        #     p.applyExternalForce(env.DRONE_IDS[0],
        #                          4,
        #                          forceObj=[0, 0, env.GRAVITY],
        #                          posObj=[0, 0, 0],
        #                          flags=p.LINK_FRAME,
        #                          physicsClientId=PYB_CLIENT
        #                          )
        if i/env.SIM_FREQ > ARM_TIME+.1:
            thro = 1660
            yaw = 1500
            pitch = 1500
            roll = 1500

        if i/env.SIM_FREQ > ARM_TIME+2.:
            thro = 1660
            yaw = 1501
            pitch = 1500
            roll = 1500

            # z PD control
            # pos_err = 2.0 - o[2]
            # vel_err = 0.0 - o[12]
            # thro = int(1666 + 50*pos_err + 20*vel_err)
        
        #### RC message to Betaflight ##############################
        aux1 = 1000 if i/env.SIM_FREQ < ARM_TIME else 1500 # Arm
        rc_packet = struct.pack('@dHHHHHHHHHHHHHHHH', 
                            i/env.SIM_FREQ, # datetime.now().timestamp(), # double timestamp; // in seconds
                            roll, pitch, thro, yaw,              # roll, pitch, throttle, yaw
                            aux1, 1000, 1000, 1000,              # aux 1, ..
                            1000, 1000, 1000, 1000, 
                            1000, 1000, 1000, 1000               # uint16_t channels[SIMULATOR_MAX_RC_CHANNELS]; // RC channels (16)
                            )
        # print("rc", struct.unpack('@dHHHHHHHHHHHHHHHH', rc_packet))
        sock.sendto(rc_packet, (UDP_IP, 9004))

        #### PWMs message from Betaflight ##########################
        try:
            data, addr = sock_pwm.recvfrom(16) # buffer size is 100 bytes (servo_packet size 16)
        except socket.error as msg:
            # print(msg)
            pass
        else:
            # print("received message: ", data)
            print('SERVO:', struct.unpack('@ffff', data))
            print('####################################################################################################')
            betaflight_pwms = np.array(struct.unpack('@ffff', data))
            remapped_input = np.array([
                                        betaflight_pwms[2], # 0
                                        betaflight_pwms[1], # 1
                                        betaflight_pwms[3], # 2
                                        betaflight_pwms[0] # 3
                                    ]) # TODO : check order, should it be 3-2-0-1?, inb edit reacer.urdf, BaseAviary.py
            action =  {'0': env.MAX_RPM * remapped_input}
        # servo_packet = struct.pack('!ffff', 
        #                     0, 0, 0, 0      # float motor_speed[4];   // normal: [0.0, 1.0], 3D: [-1.0, 1.0]
        #                     )

        #### Raw servo message from Betaflight #####################
        # try:
        #     data, addr = sock_raw.recvfrom(68) # packet size 68
        # except socket.error as msg:
        #     # print(msg)
        #     pass
        # else:
        #     pass
        #     # print("received message: ", data)
        #     # print(i/env.SIM_FREQ, ': raw', struct.unpack('@Hffffffffffffffff', data))
        # servo_packet_raw = struct.pack('!Hffffffffffffffff',
        #                     4,                                  # uint16_t motorCount; // Count of motor in the PWM output.
        #                     1100.0, 1100.0, 1100.0, 1100.0, 
        #                     1100.0, 1100.0, 1100.0, 1100.0, 
        #                     1100.0, 1100.0, 1100.0, 1100.0, 
        #                     1100.0, 1100.0, 1100.0, 1100.0      # float pwm_output_raw[SIMULATOR_MAX_PWM_CHANNELS]; (16)  // Raw PWM from 1100 to 1900
        #                     )

        #### Log the simulation ####################################
        logger.log(drone=0,
                    timestamp=i/env.SIM_FREQ,
                    state=obs['0']["state"]
                    )

        #### Printout ##############################################
        if i%env.SIM_FREQ == 0:
            env.render()

        #### Sync the simulation ###################################
        if gui:
            pass
            sync(i, START, env.TIMESTEP)

    #### Close the environment #################################
    env.close()

    #### Save the simulation results ###########################
    logger.save()
    logger.save_as_csv("beta") # Optional CSV save

    #### Plot the simulation results ###########################
    if plot:
        logger.plot()

if __name__ == "__main__":
    #### Define and parse (optional) arguments for the script ##
    parser = argparse.ArgumentParser(description='Test flight script using SITL Betaflight')
    parser.add_argument('--drone',              default=DEFAULT_DRONES,     type=DroneModel,    help='Drone model (default: RACE)', metavar='', choices=DroneModel)
    parser.add_argument('--physics',            default=DEFAULT_PHYSICS,      type=Physics,       help='Physics updates (default: PYB)', metavar='', choices=Physics)
    parser.add_argument('--gui',                default=DEFAULT_GUI,       type=str2bool,      help='Whether to use PyBullet GUI (default: True)', metavar='')
    parser.add_argument('--plot',               default=DEFAULT_PLOT,       type=str2bool,      help='Whether to plot the simulation results (default: True)', metavar='')
    parser.add_argument('--user_debug_gui',     default=DEFAULT_USER_DEBUG_GUI,      type=str2bool,      help='Whether to add debug lines and parameters to the GUI (default: False)', metavar='')
    parser.add_argument('--aggregate',          default=DEFAULT_AGGREGATE,       type=str2bool,      help='Whether to aggregate physics steps (default: True)', metavar='')
    parser.add_argument('--simulation_freq_hz', default=DEFAULT_SIMULATION_FREQ_HZ,        type=int,           help='Simulation frequency in Hz (default: 240)', metavar='')
    parser.add_argument('--control_freq_hz',    default=DEFAULT_CONTROL_FREQ_HZ,         type=int,           help='Control frequency in Hz (default: 48)', metavar='')
    parser.add_argument('--duration_sec',       default=DEFAULT_DURATION_SEC,         type=int,           help='Duration of the simulation in seconds (default: 5)', metavar='')
    parser.add_argument('--output_folder',     default=DEFAULT_OUTPUT_FOLDER, type=str,           help='Folder where to save logs (default: "results")', metavar='')
    ARGS = parser.parse_args()

    run(**vars(ARGS))
