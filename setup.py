from setuptools import setup

package_name = 'gym_pybullet_drones'

setup(
    name=package_name,
    version='1.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Jacopo Panerati',
    maintainer_email='jacopo.panerati@utoronto.ca',
    description='PyBullet Gym environments for single and multi-agent reinforcement learning of quadcopter control',
    license='MIT',
    tests_require=['pytest'],
)
