from common_fixtures import *  # NOQA
from cattle import ApiError

TEST_SERVICE_OPT_IMAGE = 'ibuildthecloud/helloworld'
TEST_SERVICE_OPT_IMAGE_LATEST = TEST_SERVICE_OPT_IMAGE + ':latest'
TEST_SERVICE_OPT_IMAGE_UUID = 'docker:' + TEST_SERVICE_OPT_IMAGE_LATEST

LB_IMAGE_UUID = "docker:sangeetha/testlbsd:latest"
SSH_IMAGE_UUID = "docker:sangeetha/testclient:latest"


docker_config_running = [{"docker_param_name": "State.Running",
                         "docker_param_value": "true"}]

docker_config_stopped = [{"docker_param_name": "State.Running",
                          "docker_param_value": "false"}]

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

total_time = [0]
shared_env = []


@pytest.fixture(scope='session', autouse=True)
def create_env_for_activate_deactivate(request, client, super_client):
    service, env = create_env_and_svc_activate(super_client, client, 3, False)
    shared_env.append({"service": service,
                       "env": env})

    def fin():
        to_delete = [env]
        delete_all(client, to_delete)

    request.addfinalizer(fin)


def deactivate_activate_service(super_client, client, service):

    # Deactivate service
    service = service.deactivate()
    service = client.wait_success(service, 300)
    assert service.state == "inactive"
    # Activate Service
    service = service.activate()
    service = client.wait_success(service, 300)
    assert service.state == "active"
    return service


def create_env_and_svc_activate(super_client, client, scale, check=True):
    launch_config = {"imageUuid": TEST_IMAGE_UUID}
    service, env = create_env_and_svc_activate_launch_config(
        super_client, client, launch_config, scale, check)
    return service, env


def create_env_and_svc_activate_launch_config(
        super_client, client, launch_config, scale, check=True):
    start_time = time.time()
    service, env = create_env_and_svc(client, launch_config, scale)
    service = service.activate()
    service = client.wait_success(service, 300)
    assert service.state == "active"
    if check:
        check_container_in_service(super_client, service)
    time_taken = time.time() - start_time
    total_time[0] = total_time[0] + time_taken
    logger.info("time taken - " + str(time_taken))
    logger.info("total time taken - " + str(total_time[0]))
    return service, env


def test_services_docker_options(super_client, client, socat_containers):

    hosts = client.list_host(kind='docker', removed_null=True, state="active")

    con_host = hosts[0]

    vol_container = client.create_container(imageUuid=TEST_IMAGE_UUID,
                                            name=random_str(),
                                            requestedHostId=con_host.id
                                            )

    vol_container = client.wait_success(vol_container)

    volume_in_host = "/test/container"
    volume_in_container = "/test/vol1"
    docker_vol_value = volume_in_host + ":" + volume_in_container + ":ro"

    cap_add = ["CHOWN"]
    cap_drop = ["KILL"]
    restart_policy = {"maximumRetryCount": 10, "name": "on-failure"}
    dns_search = ['1.2.3.4']
    dns_name = ['1.2.3.4']
    domain_name = "rancher.io"
    host_name = "test"
    user = "root"
    command = ["sleep", "9000"]
    env_var = {"TEST_FILE": "/etc/testpath.conf"}
    memory = 8000000
    cpu_set = "0"
    cpu_shares = 400

    launch_config = {"imageUuid": TEST_SERVICE_OPT_IMAGE_UUID,
                     "command": command,
                     "dataVolumes": [docker_vol_value],
                     "dataVolumesFrom": [vol_container.id],
                     "environment": env_var,
                     "capAdd": cap_add,
                     "capDrop": cap_drop,
                     "dnsSearch": dns_search,
                     "dns": dns_name,
                     "privileged": True,
                     "domainName": domain_name,
                     "stdinOpen": True,
                     "tty": True,
                     "memory": memory,
                     "cpuSet": cpu_set,
                     "cpuShares": cpu_shares,
                     "restartPolicy": restart_policy,
                     "directory": "/",
                     "hostname": host_name,
                     "user": user,
                     "requestedHostId": con_host.id
                     }

    scale = 2

    service, env = create_env_and_svc(client, launch_config,
                                      scale)

    env = env.activateservices()
    service = client.wait_success(service, 300)
    assert service.state == "active"

    check_container_in_service(super_client, service)

    container_list = get_service_container_list(super_client, service)
    for c in container_list:
        docker_client = get_docker_client(c.hosts()[0])
        inspect = docker_client.inspect_container(c.externalId)

        assert inspect["HostConfig"]["Binds"] == [docker_vol_value]
        assert inspect["HostConfig"]["VolumesFrom"] == \
            [vol_container.externalId]
        assert inspect["HostConfig"]["PublishAllPorts"] is False
        assert inspect["HostConfig"]["Privileged"] is True
        assert inspect["Config"]["OpenStdin"] is True
        assert inspect["Config"]["Tty"] is True
        assert inspect["HostConfig"]["Dns"] == dns_name
        assert inspect["HostConfig"]["DnsSearch"] == dns_search
        assert inspect["Config"]["Hostname"] == host_name
        assert inspect["Config"]["Domainname"] == domain_name
        assert inspect["Config"]["User"] == user
        assert inspect["HostConfig"]["CapAdd"] == cap_add
        assert inspect["HostConfig"]["CapDrop"] == cap_drop
        assert inspect["Config"]["Cpuset"] == cpu_set
#       No support for restart
        assert inspect["HostConfig"]["RestartPolicy"]["Name"] == ""
        assert \
            inspect["HostConfig"]["RestartPolicy"]["MaximumRetryCount"] == 0
        assert inspect["Config"]["Cmd"] == command
        assert inspect["Config"]["Memory"] == memory
        assert "TEST_FILE=/etc/testpath.conf" in inspect["Config"]["Env"]
        assert inspect["Config"]["CpuShares"] == cpu_shares

    delete_all(client, [env])


def test_services_port_and_link_options(super_client, client,
                                        socat_containers):

    hosts = client.list_host(kind='docker', removed_null=True, state="active")

    host = hosts[0]
    link_host = hosts[1]

    link_name = "WEB1"
    link_port = 80
    exposed_port = 9999

    link_container = client.create_container(
        imageUuid=LB_IMAGE_UUID,
        environment={'CONTAINER_NAME': link_name},
        name=random_str(),
        requestedHostId=host.id
        )

    link_container = client.wait_success(link_container)

    launch_config = {"imageUuid": SSH_IMAGE_UUID,
                     "ports": [str(exposed_port)+":22/tcp"],
                     "instanceLinks": {
                         link_name:
                             link_container.id},
                     "requestedHostId": link_host.id,
                     }

    service, env = create_env_and_svc(client, launch_config, 1)

    env = env.activateservices()
    service = client.wait_success(service, 300)

    container_name = env.name + "_" + service.name + "_1"
    containers = client.list_container(name=container_name, state="running")
    assert len(containers) == 1
    con = containers[0]

    validate_exposed_port_and_container_link(super_client, con, link_name,
                                             link_port, exposed_port)

    delete_all(client, [env, link_container])


def test_services_multiple_expose_port(super_client, client):

    public_port = range(2080, 2092)
    private_port = range(80, 92)
    port_mapping = []
    for i in range(0, len(public_port)):
        port_mapping.append(str(public_port[i])+":" +
                            str(private_port[i]) + "/tcp")
    launch_config = {"imageUuid": MULTIPLE_EXPOSED_PORT_UUID,
                     "ports": port_mapping,
                     }

    service, env = create_env_and_svc(client, launch_config, 3)

    env = env.activateservices()
    service = client.wait_success(service, 300)

    validate_exposed_port(super_client, service, public_port)

    delete_all(client, [env])


def test_services_random_expose_port(super_client, client):

    launch_config = {"imageUuid": MULTIPLE_EXPOSED_PORT_UUID,
                     "ports": ["80/tcp", "81/tcp"]
                     }
    service, env = create_env_and_svc(client, launch_config, 3)

    env = env.activateservices()
    service = client.wait_success(service, 300)

    port = service.launchConfig["ports"][0]
    exposedPort1 = int(port[0:port.index(":")])
    assert exposedPort1 in range(49153, 65535)

    port = service.launchConfig["ports"][1]
    exposedPort2 = int(port[0:port.index(":")])
    assert exposedPort2 in range(49153, 65535)

    print service.publicEndpoints
    validate_exposed_port(super_client, service, [exposedPort1, exposedPort2])

    delete_all(client, [env])


def test_services_random_expose_port_exhaustrange(
        super_client, admin_client, client):

    # Set random port range to 6 ports and exhaust 5 of them by creating a
    # service that has 5 random ports exposed
    project = admin_client.list_project()[0]
    admin_client.update(
        project, servicesPortRange={"startPort": 65500, "endPort": 65505})

    launch_config = {"imageUuid": MULTIPLE_EXPOSED_PORT_UUID,
                     "ports":
                         ["80/tcp", "81/tcp", "82/tcp", "83/tcp", "84/tcp"]
                     }

    service, env = create_env_and_svc(client, launch_config, 3)

    env = env.activateservices()
    service = client.wait_success(service, 60)
    assert service.publicEndpoints is not None
    assert len(service.publicEndpoints) == 15

    exposedPorts = []
    for i in range(0, 5):
        port = service.launchConfig["ports"][0]
        exposedPort = int(port[0:port.index(":")])
        exposedPorts.append(exposedPort)
        assert exposedPort in range(65500, 65506)

    validate_exposed_port(super_client, service, exposedPorts)

    # Create a service that has 2 random exposed ports when there is only 1
    # free port available in the random port range
    # Validate that the service gets created with no ports exposed

    launch_config = {"imageUuid": MULTIPLE_EXPOSED_PORT_UUID,
                     "ports":
                         ["80/tcp", "81/tcp"]
                     }

    service1, env1 = create_env_and_svc(client, launch_config, 3)
    env1 = env1.activateservices()
    service1 = client.wait_success(service1, 60)
    assert service1.publicEndpoints is None

    # Delete the service that consumed 5 random ports
    delete_all(client, [env])

    # Create a service that has 2 random exposed ports and validate that
    # the service gets exposed in 2 random ports from the range

    service2, env2 = create_env_and_svc(client, launch_config, 3)
    env2 = env2.activateservices()
    service2 = client.wait_success(service2, 60)
    assert service2.publicEndpoints is not None
    assert len(service2.publicEndpoints) == 6

    exposedPorts = []
    for i in range(0, 2):
        port = service2.launchConfig["ports"][0]
        exposedPort = int(port[0:port.index(":")])
        exposedPorts.append(exposedPort)
        assert exposedPort in range(65500, 65506)

    validate_exposed_port(super_client, service2, exposedPorts)

    delete_all(client, [env1, env2])


def test_environment_activate_deactivate_delete(super_client,
                                                client,
                                                socat_containers):

    launch_config = {"imageUuid": TEST_IMAGE_UUID}

    scale = 1

    service1, env = create_env_and_svc(client, launch_config,
                                       scale)

    service2 = create_svc(client, env, launch_config, scale)

    # Environment Activate Services
    env = env.activateservices()

    service1 = client.wait_success(service1, 300)
    assert service1.state == "active"
    check_container_in_service(super_client, service1)

    service2 = client.wait_success(service2, 300)
    assert service2.state == "active"
    check_container_in_service(super_client, service2)

    # Environment Deactivate Services
    env = env.deactivateservices()

    wait_until_instances_get_stopped(super_client, service1)
    wait_until_instances_get_stopped(super_client, service2)

    service1 = client.wait_success(service1, 300)
    assert service1.state == "inactive"
    check_stopped_container_in_service(super_client, service1)

    service2 = client.wait_success(service2, 300)
    assert service2.state == "inactive"
    check_stopped_container_in_service(super_client, service2)

    # Environment Activate Services
    env = env.activateservices()

    service1 = client.wait_success(service1, 300)
    assert service1.state == "active"
    check_container_in_service(super_client, service1)

    service2 = client.wait_success(service2, 300)
    assert service2.state == "active"
    check_container_in_service(super_client, service2)

    # Delete Environment
    env = client.wait_success(client.delete(env))
    assert env.state == "removed"

    # Deleting service results in instances of the service to be "removed".
    # instance continues to be part of service , until the instance is purged.

    check_for_deleted_service(super_client, env, service1)
    check_for_deleted_service(super_client, env, service2)

    delete_all(client, [env])


def test_service_activate_deactivate_delete(super_client, client,
                                            socat_containers):

    launch_config = {"imageUuid": TEST_IMAGE_UUID}

    scale = 2

    service, env = create_env_and_svc(client, launch_config,
                                      scale)
    # Activate Services
    service = service.activate()
    service = client.wait_success(service, 300)
    assert service.state == "active"

    check_container_in_service(super_client, service)

    # Deactivate Services
    service = service.deactivate()
    service = client.wait_success(service, 300)
    assert service.state == "inactive"
    wait_until_instances_get_stopped(super_client, service)
    check_stopped_container_in_service(super_client, service)

    # Activate Services
    service = service.activate()
    service = client.wait_success(service, 300)
    assert service.state == "active"

    check_container_in_service(super_client, service)

    # Delete Service
    service = client.wait_success(client.delete(service))
    assert service.state == "removed"

    check_for_deleted_service(super_client, env, service)

    delete_all(client, [env])


def test_service_activate_stop_instance(
        super_client, client, socat_containers):

    service = shared_env[0]["service"]
    check_for_service_reconciliation_on_stop(super_client, client, service)


def test_service_activate_delete_instance(
        super_client, client, socat_containers):

    service = shared_env[0]["service"]
    check_for_service_reconciliation_on_delete(super_client, client, service)


def test_service_activate_purge_instance(
        super_client, client, socat_containers):

    service = shared_env[0]["service"]

    # Purge 2 instances
    containers = get_service_container_list(super_client, service)
    container1 = containers[0]
    container1 = client.wait_success(client.delete(container1))
    container1 = client.wait_success(container1.purge())
    container2 = containers[1]
    container2 = client.wait_success(client.delete(container2))
    container2 = client.wait_success(container2.purge())

    wait_for_scale_to_adjust(super_client, service)

    check_container_in_service(super_client, service)


def test_service_activate_restore_instance(
        super_client, client, socat_containers):

    service = shared_env[0]["service"]

    # Restore 2 instances
    containers = get_service_container_list(super_client, service)
    container1 = containers[0]
    container1 = client.wait_success(client.delete(container1))
    container1 = client.wait_success(container1.restore())
    container2 = containers[1]
    container2 = client.wait_success(client.delete(container2))
    container2 = client.wait_success(container2.restore())

    assert container1.state == "stopped"
    assert container2.state == "stopped"

    wait_for_scale_to_adjust(super_client, service)

    check_container_in_service(super_client, service)
    delete_all(client, [container1, container2])


def test_service_scale_up(super_client, client, socat_containers):
    check_service_scale(super_client, client, socat_containers, 2, 4)


def test_service_scale_down(super_client, client, socat_containers):
    check_service_scale(super_client, client, socat_containers, 4, 2, 2)


def test_service_activate_stop_instance_scale_up(
        super_client, client, socat_containers):
    check_service_activate_stop_instance_scale(
        super_client, client, socat_containers, 3, 4, [1])


def test_service_activate_delete_instance_scale_up(
        super_client, client, socat_containers):
    check_service_activate_delete_instance_scale(
        super_client, client, socat_containers, 3, 4, [1])


def test_service_activate_stop_instance_scale_down(
        super_client, client, socat_containers):
    check_service_activate_stop_instance_scale(
        super_client, client, socat_containers, 4, 1, [1], 3)


def test_service_activate_delete_instance_scale_down(
        super_client, client, socat_containers):
    check_service_activate_delete_instance_scale(
        super_client, client, socat_containers, 4, 1, [1], 3)


def test_service_activate_stop_instance_scale_up_1(
        super_client, client, socat_containers):
    check_service_activate_stop_instance_scale(
        super_client, client, socat_containers, 3, 4, [3])


def test_service_activate_delete_instance_scale_up_1(
        super_client, client, socat_containers):
    check_service_activate_delete_instance_scale(
        super_client, client, socat_containers, 3, 4, [3])


def test_service_activate_stop_instance_scale_down_1(
        super_client, client, socat_containers):
    check_service_activate_stop_instance_scale(
        super_client, client, socat_containers, 4, 1, [4], 3)


def test_service_activate_delete_instance_scale_down_1(
        super_client, client, socat_containers):
    check_service_activate_delete_instance_scale(super_client, client,
                                                 socat_containers,
                                                 4, 1, [4], 3)


def test_service_activate_stop_instance_scale_up_2(
        super_client, client, socat_containers):
    check_service_activate_stop_instance_scale(
        super_client, client, socat_containers, 3, 4, [1, 2, 3])


def test_service_activate_delete_instance_scale_up_2(
        super_client, client, socat_containers):
    check_service_activate_delete_instance_scale(
        super_client, client, socat_containers, 3, 4, [1, 2, 3])


def test_service_activate_stop_instance_scale_down_2(
        super_client, client, socat_containers):
    check_service_activate_stop_instance_scale(
        super_client, client, socat_containers, 4, 1, [1, 2, 3, 4], 3)


def test_service_activate_delete_instance_scale_down_2(
        super_client, client, socat_containers):
    check_service_activate_delete_instance_scale(
        super_client, client, socat_containers, 4, 1, [1, 2, 3, 4])


def test_service_activate_stop_instance_scale_up_3(
        super_client, client, socat_containers):
    check_service_activate_stop_instance_scale(
        super_client, client, socat_containers, 3, 4, [2])


def test_service_activate_delete_instance_scale_up_3(
        super_client, client, socat_containers):
    check_service_activate_delete_instance_scale(
        super_client, client, socat_containers, 3, 4, [2])


def test_service_activate_stop_instance_scale_down_3(
        super_client, client, socat_containers):
    check_service_activate_stop_instance_scale(
        super_client, client, socat_containers, 4, 1, [2], 3)


def test_service_activate_delete_instance_scale_down_3(
        super_client, client, socat_containers):
    check_service_activate_delete_instance_scale(
        super_client, client, socat_containers, 4, 1, [2], 3)


def test_services_hostname_override_1(super_client, client, socat_containers):

    host_name = "test"
    domain_name = "abc.com"

    launch_config = {"imageUuid": TEST_IMAGE_UUID,
                     "domainName": domain_name,
                     "hostname": host_name,
                     "labels":
                         {"io.rancher.container.hostname_override":
                          "container_name"}
                     }

    scale = 2

    service, env = create_env_and_svc(client, launch_config,
                                      scale)

    env = env.activateservices()
    service = client.wait_success(service, 300)
    assert service.state == "active"

    check_container_in_service(super_client, service)

    container_list = get_service_container_list(super_client, service)
    assert len(container_list) == service.scale
    print container_list
    for c in container_list:
        docker_client = get_docker_client(c.hosts()[0])
        inspect = docker_client.inspect_container(c.externalId)

        assert inspect["Config"]["Hostname"] == c.name

    delete_all(client, [env])


def test_services_hostname_override_2(super_client, client, socat_containers):

    launch_config = {"imageUuid": TEST_IMAGE_UUID,
                     "labels":
                         {"io.rancher.container.hostname_override":
                          "container_name"}
                     }

    scale = 2

    service, env = create_env_and_svc(client, launch_config,
                                      scale)

    env = env.activateservices()
    service = client.wait_success(service, 300)
    assert service.state == "active"

    check_container_in_service(super_client, service)

    container_list = get_service_container_list(super_client, service)
    assert len(container_list) == service.scale
    for c in container_list:
        docker_client = get_docker_client(c.hosts()[0])
        inspect = docker_client.inspect_container(c.externalId)

        assert inspect["Config"]["Hostname"] == c.name

    delete_all(client, [env])


def test_service_reconcile_stop_instance_restart_policy_always(
        super_client, client, socat_containers):
    scale = 3
    launch_config = {"imageUuid": TEST_IMAGE_UUID,
                     "restartPolicy": {"name": "always"}}
    service, env = create_env_and_svc_activate_launch_config(
        super_client, client, launch_config, scale)
    check_for_service_reconciliation_on_stop(super_client, client, service)
    delete_all(client, [env])


def test_service_reconcile_delete_instance_restart_policy_always(
        super_client, client, socat_containers):
    scale = 3
    launch_config = {"imageUuid": TEST_IMAGE_UUID,
                     "restartPolicy": {"name": "always"}}
    service, env = create_env_and_svc_activate_launch_config(
        super_client, client, launch_config, scale)
    check_for_service_reconciliation_on_delete(super_client, client, service)
    delete_all(client, [env])


def test_service_reconcile_delete_instance_restart_policy_no(
        super_client, client, socat_containers):
    scale = 3
    launch_config = {"imageUuid": TEST_IMAGE_UUID,
                     "labels": {"io.rancher.container.start_once": True}
                     }
    service, env = create_env_and_svc_activate_launch_config(
        super_client, client, launch_config, scale)
    check_for_service_reconciliation_on_delete(super_client, client, service)
    delete_all(client, [env])


def test_service_reconcile_stop_instance_restart_policy_no(
        super_client, client, socat_containers):
    scale = 3
    launch_config = {"imageUuid": TEST_IMAGE_UUID,
                     "labels": {"io.rancher.container.start_once": True}}
    service, env = create_env_and_svc_activate_launch_config(
        super_client, client, launch_config, scale)

    # Stop 2 containers of the service
    assert service.scale > 1
    containers = get_service_container_list(super_client, service)
    assert len(containers) == service.scale
    assert service.scale > 1
    container1 = containers[0]
    container1 = client.wait_success(container1.stop())
    container2 = containers[1]
    container2 = client.wait_success(container2.stop())

    service = client.wait_success(service)
    time.sleep(30)
    assert service.state == "active"

    # Make sure that the containers continue to remain in "stopped" state
    container1 = client.reload(container1)
    container2 = client.reload(container2)
    assert container1.state == 'stopped'
    assert container2.state == 'stopped'
    delete_all(client, [env])


def test_service_reconcile_stop_instance_restart_policy_failure(
        super_client, client, socat_containers):
    scale = 3
    launch_config = {"imageUuid": TEST_IMAGE_UUID,
                     "restartPolicy": {"name": "on-failure"}
                     }
    service, env = create_env_and_svc_activate_launch_config(
        super_client, client, launch_config, scale)
    check_for_service_reconciliation_on_stop(super_client, client, service)
    delete_all(client, [env])


def test_service_reconcile_delete_instance_restart_policy_failure(
        super_client, client, socat_containers):
    scale = 3
    launch_config = {"imageUuid": TEST_IMAGE_UUID,
                     "restartPolicy": {"name": "on-failure"}
                     }
    service, env = create_env_and_svc_activate_launch_config(
        super_client, client, launch_config, scale)
    check_for_service_reconciliation_on_delete(super_client, client, service)
    delete_all(client, [env])


def test_service_reconcile_stop_instance_restart_policy_failure_count(
        super_client, client, socat_containers):
    scale = 3
    launch_config = {"imageUuid": TEST_IMAGE_UUID,
                     "restartPolicy": {"maximumRetryCount": 5,
                                       "name": "on-failure"}
                     }
    service, env = create_env_and_svc_activate_launch_config(
        super_client, client, launch_config, scale)
    check_for_service_reconciliation_on_stop(super_client, client, service)
    delete_all(client, [env])


def test_service_reconcile_delete_instance_restart_policy_failure_count(
        super_client, client, socat_containers):
    scale = 3
    launch_config = {"imageUuid": TEST_IMAGE_UUID,
                     "restartPolicy": {"maximumRetryCount": 5,
                                       "name": "on-failure"}
                     }
    service, env = create_env_and_svc_activate_launch_config(
        super_client, client, launch_config, scale)
    check_for_service_reconciliation_on_delete(super_client, client, service)
    delete_all(client, [env])


def test_service_with_healthcheck(super_client, client, socat_containers):
    scale = 3
    env, service = service_with_healthcheck_enabled(
        client, super_client, scale)
    delete_all(client, [env])


def test_service_with_healthcheck_none(super_client, client, socat_containers):
    scale = 3
    env, service = service_with_healthcheck_enabled(
        client, super_client, scale, strategy="none")
    delete_all(client, [env])


def test_service_with_healthcheck_recreate(
        super_client, client, socat_containers):
    scale = 10
    env, service = service_with_healthcheck_enabled(
        client, super_client, scale, strategy="recreate")
    delete_all(client, [env])


def test_service_with_healthcheck_recreateOnQuorum(
        super_client, client, socat_containers):
    scale = 10
    env, service = service_with_healthcheck_enabled(
        client, super_client, scale, strategy="recreateOnQuorum", qcount=5)
    delete_all(client, [env])


def test_service_with_healthcheck_container_unhealthy(
        super_client, client, socat_containers):
    scale = 2
    port = 9998

    env, service = service_with_healthcheck_enabled(client, super_client,
                                                    scale, port)

    # Delete requestUrl from one of the containers to trigger health check
    # failure and service reconcile
    container_list = get_service_container_list(super_client, service)
    con = container_list[1]
    mark_container_unhealthy(con, port)

    wait_for_condition(
        client, con,
        lambda x: x.healthState == 'unhealthy',
        lambda x: 'State is: ' + x.healthState)
    con = client.reload(con)
    assert con.healthState == "unhealthy"

    wait_for_condition(
        client, con,
        lambda x: x.state in ('removed', 'purged'),
        lambda x: 'State is: ' + x.healthState)
    wait_for_scale_to_adjust(super_client, service)
    con = client.reload(con)
    assert con.state in ('removed', 'purged')

    container_list = get_service_container_list(super_client, service)
    for con in container_list:
        wait_for_condition(
            client, con,
            lambda x: x.healthState == 'healthy',
            lambda x: 'State is: ' + x.healthState)
    delete_all(client, [env])


def test_service_with_healthcheck_none_container_unhealthy(
        super_client, client, socat_containers):
    scale = 3
    port = 801

    env, service = service_with_healthcheck_enabled(client, super_client,
                                                    scale, port,
                                                    strategy="none")

    # Delete requestUrl from one of the containers to trigger health check
    # failure and service reconcile
    container_list = get_service_container_list(super_client, service)
    con1 = container_list[1]
    mark_container_unhealthy(con1, port)

    # Validate that the container is marked unhealthy
    wait_for_condition(
        client, con1,
        lambda x: x.healthState == 'unhealthy',
        lambda x: 'State is: ' + x.healthState)
    con1 = client.reload(con1)
    assert con1.healthState == "unhealthy"

    # Make sure that the container continues to be marked unhealthy
    # and is in "Running" state

    time.sleep(10)
    con1 = client.reload(con1)
    assert con1.healthState == "unhealthy"
    assert con1.state == "running"

    mark_container_healthy(container_list[1], port)
    # Make sure that the container gets marked healthy

    wait_for_condition(
        client, con1,
        lambda x: x.healthState == 'healthy',
        lambda x: 'State is: ' + x.healthState)
    con1 = client.reload(con1)
    assert con1.healthState == "healthy"
    assert con1.state == "running"

    delete_all(client, [env])


def test_service_with_healthcheck_none_container_unhealthy_delete(
        super_client, client, socat_containers):
    scale = 3
    port = 801

    env, service = service_with_healthcheck_enabled(client, super_client,
                                                    scale, port,
                                                    strategy="none")

    # Delete requestUrl from containers to trigger health check
    # failure and service reconcile
    container_list = get_service_container_list(super_client, service)
    unhealthy_containers = [container_list[0],
                            container_list[1]]

    for con in unhealthy_containers:
        mark_container_unhealthy(con, port)

    # Validate that the container is marked unhealthy
    for con in unhealthy_containers:
        wait_for_condition(
            client, con,
            lambda x: x.healthState == 'unhealthy',
            lambda x: 'State is: ' + x.healthState)
        con = client.reload(con)
        assert con.healthState == "unhealthy"

    # Make sure that the container continues to be marked unhealthy
    # and is in "Running" state

    time.sleep(10)
    for con in unhealthy_containers:
        con = client.reload(con)
        assert con.healthState == "unhealthy"
        assert con.state == "running"

    # Delete 2 containers that are unhealthy
    for con in unhealthy_containers:
        container = client.wait_success(client.delete(con))
        assert container.state == 'removed'

    # Validate that the service reconciles on deletion of unhealthy containers
    wait_for_scale_to_adjust(super_client, service)
    check_container_in_service(super_client, service)

    # Validate that all containers of the service get to "healthy" state
    container_list = get_service_container_list(super_client, service)
    for con in container_list:
        wait_for_condition(
            client, con,
            lambda x: x.healthState == 'healthy',
            lambda x: 'State is: ' + x.healthState)
    delete_all(client, [env])


def test_service_with_healthcheck_quorum_containers_unhealthy_1(
        super_client, client, socat_containers):
    scale = 2
    port = 802

    env, service = service_with_healthcheck_enabled(
        client, super_client, scale, port, strategy="recreateOnQuorum",
        qcount=1)

    # Make 1 container unhealthy , so there is 1 container that is healthy
    container_list = get_service_container_list(super_client, service)
    con1 = container_list[1]
    mark_container_unhealthy(con1, port)

    # Validate that the container is marked unhealthy
    wait_for_condition(
        client, con1,
        lambda x: x.healthState == 'unhealthy',
        lambda x: 'State is: ' + x.healthState)
    con1 = client.reload(con1)
    assert con1.healthState == "unhealthy"

    # Validate that the containers get removed
    wait_for_condition(
        client, con1,
        lambda x: x.state in ('removed', 'purged'),
        lambda x: 'State is: ' + x.healthState)
    wait_for_scale_to_adjust(super_client, service)
    con = client.reload(con1)
    assert con.state in ('removed', 'purged')

    # Validate that the service reconciles
    container_list = get_service_container_list(super_client, service)
    for con in container_list:
        wait_for_condition(
            client, con,
            lambda x: x.healthState == 'healthy',
            lambda x: 'State is: ' + x.healthState)
    delete_all(client, [env])


def test_service_with_healthcheck_quorum_container_unhealthy_2(
        super_client, client, socat_containers):
    scale = 3
    port = 803

    env, service = service_with_healthcheck_enabled(
        client, super_client, scale, port, strategy="recreateOnQuorum",
        qcount=2)

    # Make 2 containers unhealthy , so 1 container is healthy state
    container_list = get_service_container_list(super_client, service)

    unhealthy_containers = [container_list[1],
                            container_list[2]]

    for con in unhealthy_containers:
        mark_container_unhealthy(con, port)

    # Validate that the container is marked unhealthy
    for con in unhealthy_containers:
        wait_for_condition(
            client, con,
            lambda x: x.healthState == 'unhealthy',
            lambda x: 'State is: ' + x.healthState)
        con = client.reload(con)
        assert con.healthState == "unhealthy"

    # Make sure that the container continues to be marked unhealthy
    # and is in "Running" state
    time.sleep(10)
    for con in unhealthy_containers:
        con = client.reload(con)
        assert con.healthState == "unhealthy"
        assert con.state == "running"

    delete_all(client, [env])


def test_dns_service_with_healthcheck_none_container_unhealthy(
        super_client, client, socat_containers):

    scale = 3
    port = 804
    cport = 805

    # Create HealthCheck enabled Service
    env, service = service_with_healthcheck_enabled(client, super_client,
                                                    scale, port,
                                                    strategy="none")
    # Create Client Service for DNS access check
    launch_config_svc = {"imageUuid": SSH_IMAGE_UUID,
                         "ports": [str(cport)+":22/tcp"]}
    random_name = random_str()
    service_name = random_name.replace("-", "")
    client_service = client.create_service(name=service_name,
                                           environmentId=env.id,
                                           launchConfig=launch_config_svc,
                                           scale=1)
    client_service = client.wait_success(client_service)
    assert client_service.state == "inactive"
    client_service = client.wait_success(client_service.activate())
    assert client_service.state == "active"

    # Check for DNS resolution
    validate_linked_service(super_client, client_service, [service], cport)

    # Delete requestUrl from one of the containers to trigger health check
    # failure and service reconcile
    container_list = get_service_container_list(super_client, service)
    con1 = container_list[1]
    mark_container_unhealthy(con1, port)

    # Validate that the container is marked unhealthy
    wait_for_condition(
        client, con1,
        lambda x: x.healthState == 'unhealthy',
        lambda x: 'State is: ' + x.healthState)
    con1 = client.reload(con1)
    assert con1.healthState == "unhealthy"

    # Check for DNS resolution
    validate_linked_service(super_client, client_service, [service],
                            cport, exclude_instance=con1)

    # Make sure that the container continues to be marked unhealthy
    # and is in "Running" state

    time.sleep(10)
    con1 = client.reload(con1)
    assert con1.healthState == "unhealthy"
    assert con1.state == "running"

    mark_container_healthy(container_list[1], port)

    # Make sure that the container gets marked healthy

    wait_for_condition(
        client, con1,
        lambda x: x.healthState == 'healthy',
        lambda x: 'State is: ' + x.healthState)
    con1 = client.reload(con1)
    assert con1.healthState == "healthy"
    assert con1.state == "running"

    # Check for DNS resolution
    validate_linked_service(super_client, client_service, [service], cport)

    delete_all(client, [env])


def test_service_health_check_scale_up(super_client, client, socat_containers):

    scale = 1
    final_scale = 3
    env, service = service_with_healthcheck_enabled(
        client, super_client, scale)
    # Scale service
    service = client.update(service, name=service.name, scale=final_scale)
    service = client.wait_success(service, 300)
    assert service.state == "active"
    assert service.scale == final_scale
    check_container_in_service(super_client, service)
    check_for_healthstate(client, super_client, service)
    delete_all(client, [env])


def test_service_health_check_reconcile_on_stop(
        super_client, client, socat_containers):
    scale = 3
    env, service = service_with_healthcheck_enabled(
        client, super_client, scale)
    check_for_service_reconciliation_on_stop(super_client, client, service)
    check_for_healthstate(client, super_client, service)
    delete_all(client, [env])


def test_service_health_check_reconcile_on_delete(
        super_client, client, socat_containers):
    scale = 3
    env, service = service_with_healthcheck_enabled(
        client, super_client, scale)
    check_for_service_reconciliation_on_delete(super_client, client, service)
    check_for_healthstate(client, super_client, service)
    delete_all(client, [env])


def test_service_health_check_with_tcp(
        super_client, client, socat_containers):
    scale = 3
    env, service = service_with_healthcheck_enabled(
        client, super_client, scale, protocol="tcp")
    delete_all(client, [env])


def test_service_with_healthcheck_container_tcp_unhealthy(
        super_client, client, socat_containers):
    scale = 2
    port = 9997

    env, service = service_with_healthcheck_enabled(
        client, super_client, scale, port, protocol="tcp")

    # Stop ssh service from one of the containers to trigger health check
    # failure and service reconcile
    container_list = get_service_container_list(super_client, service)
    con = container_list[1]
    hostIpAddress = con.dockerHostIp

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostIpAddress, username="root",
                password="root", port=port)
    cmd = "service ssh stop"
    logger.info(cmd)
    stdin, stdout, stderr = ssh.exec_command(cmd)

    wait_for_condition(
        client, con,
        lambda x: x.healthState == 'unhealthy',
        lambda x: 'State is: ' + x.healthState)
    con = client.reload(con)
    assert con.healthState == "unhealthy"

    wait_for_condition(
        client, con,
        lambda x: x.state in ('removed', 'purged'),
        lambda x: 'State is: ' + x.healthState)
    wait_for_scale_to_adjust(super_client, service)
    con = client.reload(con)
    assert con.state in ('removed', 'purged')

    container_list = get_service_container_list(super_client, service)
    for con in container_list:
        wait_for_condition(
            client, con,
            lambda x: x.healthState == 'healthy',
            lambda x: 'State is: ' + x.healthState)
    delete_all(client, [env])


def test_service_name_unique(super_client, client):
    launch_config = {"imageUuid": TEST_IMAGE_UUID}
    service, env = create_env_and_svc(client, launch_config, 1)
    service_name = service.name

    # Should not be allowed to create service with name when service name is
    # already used by a service in the same stack
    with pytest.raises(ApiError) as e:
        service = client.wait_success(client.create_service(name=service_name,
                                      environmentId=env.id,
                                      launchConfig=launch_config,
                                      scale=1))
    assert e.value.error.status == 422
    assert e.value.error.code == 'NotUnique'
    assert e.value.error.fieldName == "name"
    delete_all(client, [env])


def test_service_name_unique_create_after_delete(super_client, client):
    launch_config = {"imageUuid": TEST_IMAGE_UUID}
    service, env = create_env_and_svc(client, launch_config, 1)
    service_name = service.name
    # Should be allowed to create service with name when service name is
    # used by service which is already deleted in the same stack
    client.wait_success(client.delete(service))
    service = client.wait_success(client.create_service(name=service_name,
                                  environmentId=env.id,
                                  launchConfig=launch_config,
                                  scale=1))
    assert service.state == "inactive"
    delete_all(client, [env])


def test_service_name_unique_edit(super_client, client):
    launch_config = {"imageUuid": TEST_IMAGE_UUID}
    service, env = create_env_and_svc(client, launch_config, 1)
    service_name = service.name

    # Should not be allowed to edit existing service and set its name
    # to a service name that already exist in the same stack
    service = client.wait_success(client.create_service(name=random_str(),
                                  environmentId=env.id,
                                  launchConfig=launch_config,
                                  scale=1))
    with pytest.raises(ApiError) as e:
        service = client.wait_success(client.update(service, name=service_name,
                                                    scale=1))
    assert e.value.error.status == 422
    assert e.value.error.code == 'NotUnique'
    assert e.value.error.fieldName == "name"
    delete_all(client, [env])


def check_service_scale(super_client, client, socat_containers,
                        initial_scale, final_scale,
                        removed_instance_count=0):

    service, env = create_env_and_svc_activate(super_client, client,
                                               initial_scale)

    # Scale service
    service = client.update(service, name=service.name, scale=final_scale)
    service = client.wait_success(service, 300)
    assert service.state == "active"
    assert service.scale == final_scale

    check_container_in_service(super_client, service)

    # Check for destroyed containers in case of scale down
    if final_scale < initial_scale:
        check_container_removed_from_service(super_client, service, env,
                                             removed_instance_count)
    delete_all(client, [env])


def check_service_activate_stop_instance_scale(super_client, client,
                                               socat_containers,
                                               initial_scale, final_scale,
                                               stop_instance_index,
                                               removed_instance_count=0):

    service, env = create_env_and_svc_activate(super_client, client,
                                               initial_scale)

    # Stop instance
    for i in stop_instance_index:
        container_name = env.name + "_" + service.name + "_" + str(i)
        containers = client.list_container(name=container_name)
        assert len(containers) == 1
        container = containers[0]
        container = client.wait_success(container.stop(), 300)
        # assert container.state == 'stopped'
        logger.info("Stopped container - " + container_name)

    service = client.wait_success(service)

    logger.info("service being updated - " + service.name + " - " + service.id)
    # Scale service
    service = client.update(service, name=service.name, scale=final_scale)
    service = client.wait_success(service, 300)
    assert service.state == "active"
    assert service.scale == final_scale
    logger.info("Scaled service - " + str(final_scale))

    check_container_in_service(super_client, service)

    # Check for destroyed containers in case of scale down
    if final_scale < initial_scale and removed_instance_count > 0:
        check_container_removed_from_service(super_client, service, env,
                                             removed_instance_count)
    delete_all(client, [env])


def check_service_activate_delete_instance_scale(super_client, client,
                                                 socat_containers,
                                                 initial_scale, final_scale,
                                                 delete_instance_index,
                                                 removed_instance_count=0):

    service, env = create_env_and_svc_activate(super_client, client,
                                               initial_scale)

    # Delete instance
    for i in delete_instance_index:
        container_name = env.name + "_" + service.name + "_" + str(i)
        containers = client.list_container(name=container_name)
        assert len(containers) == 1
        container = containers[0]
        container = client.wait_success(client.delete(container))
        assert container.state == 'removed'
        logger.info("Delete Container -" + container_name)

    service = client.wait_success(service)
    logger.info("service being updated " + service.name + " - " + service.id)
    # Scale service
    service = client.update(service, name=service.name, scale=final_scale)
    service = client.wait_success(service, 300)
    assert service.state == "active"
    assert service.scale == final_scale
    logger.info("Scaled service - " + str(final_scale))

    check_container_in_service(super_client, service)
    """
    # Check for destroyed containers in case of scale down
    if final_scale < initial_scale and removed_instance_count > 0:
        if removed_instance_count is not None:
            check_container_removed_from_service(super_client, service, env,
                                                 removed_instance_count)
    """
    delete_all(client, [env])


def _validate_add_service_link(service, client, scale):
    service_maps = client. \
        list_serviceExposeMap(serviceId=service.id)
    assert len(service_maps) == scale
    service_map = service_maps[0]
    wait_for_condition(
        client, service_map,
        lambda x: x.state == "active",
        lambda x: 'State is: ' + x.state)


def check_stopped_container_in_service(super_client, service):

    container_list = get_service_container_list(super_client, service)

    assert len(container_list) == service.scale

    for container in container_list:
        assert container.state == "stopped"
        containers = super_client.list_container(
            externalId=container.externalId,
            include="hosts",
            removed_null=True)
        docker_client = get_docker_client(containers[0].hosts[0])
        inspect = docker_client.inspect_container(container.externalId)
        logger.info("Checked for container stopped - " + container.name)
        assert inspect["State"]["Running"] is False


def check_container_removed_from_service(super_client, service, env,
                                         removed_count):
    container = []
    instance_maps = super_client.list_serviceExposeMap(serviceId=service.id,
                                                       state="removed")
    start = time.time()

    while len(instance_maps) != removed_count:
        time.sleep(.5)
        instance_maps = super_client.list_serviceExposeMap(
            serviceId=service.id, state="removed")
        if time.time() - start > 30:
            raise Exception('Timed out waiting for Service Expose map to be ' +
                            'removed for scaled down instances')

    for instance_map in instance_maps:
        container = super_client.by_id('container', instance_map.instanceId)
        wait_for_condition(
            super_client, container,
            lambda x: x.state == "removed" or x.state == "purged",
            lambda x: 'State is: ' + x.state)
        if container.state == "removed":
            containers = super_client.list_container(name=container.name,
                                                     include="hosts")
            assert len(containers) == 1
            docker_client = get_docker_client(containers[0].hosts[0])
            inspect = docker_client.inspect_container(container.externalId)
            logger.info("Checked for containers removed from service - " +
                        container.name)
            assert inspect["State"]["Running"] is False


def check_for_deleted_service(super_client, env, service):

    service_maps = super_client.list_serviceExposeMap(serviceId=service.id)

    for service_map in service_maps:
        wait_for_condition(
            super_client, service_map,
            lambda x: x.state == "removed",
            lambda x: 'State is: ' + x.state)
        container = super_client.by_id('container', service_map.instanceId)
        wait_for_condition(
            super_client, container,
            lambda x: x.state == "purged",
            lambda x: 'State is: ' + x.state)
        logger.info("Checked for purged container - " + container.name)


def check_service_map(super_client, service, instance, state):
    instance_service_map = super_client.\
        list_serviceExposeMap(serviceId=service.id, instanceId=instance.id)
    assert len(instance_service_map) == 1
    assert instance_service_map[0].state == state


def get_service_container_list(super_client, service):

    container = []
    instance_maps = super_client.list_serviceExposeMap(serviceId=service.id,
                                                       state="active")
    start = time.time()

    while len(instance_maps) != service.scale:
        time.sleep(.5)
        instance_maps = super_client.list_serviceExposeMap(
            serviceId=service.id, state="active")
        if time.time() - start > 30:
            raise Exception('Timed out waiting for Service Expose map to be ' +
                            'created for all instances')

    for instance_map in instance_maps:
        logger.info(instance_map.instanceId + " - " + instance_map.serviceId)
        c = super_client.by_id('container', instance_map.instanceId)
        container.append(c)

    return container


def check_for_service_reconciliation_on_stop(super_client, client, service):
    # Stop 2 containers of the service
    assert service.scale > 1
    containers = get_service_container_list(super_client, service)
    assert len(containers) == service.scale
    assert service.scale > 1
    container1 = containers[0]
    container1 = client.wait_success(container1.stop())
    container2 = containers[1]
    container2 = client.wait_success(container2.stop())

    service = client.wait_success(service)

    wait_for_scale_to_adjust(super_client, service)

    check_container_in_service(super_client, service)
    container1 = client.reload(container1)
    container2 = client.reload(container2)
    assert container1.state == 'running'
    assert container2.state == 'running'


def check_for_service_reconciliation_on_delete(super_client, client, service):
    # Delete 2 containers of the service
    containers = get_service_container_list(super_client, service)
    container1 = containers[0]
    container1 = client.wait_success(client.delete(container1))
    container2 = containers[1]
    container2 = client.wait_success(client.delete(container2))

    assert container1.state == 'removed'
    assert container2.state == 'removed'

    wait_for_scale_to_adjust(super_client, service)

    check_container_in_service(super_client, service)


def service_with_healthcheck_enabled(client, super_client, scale, port=None,
                                     protocol="http", labels=None,
                                     strategy=None, qcount=None):
    health_check = {"name": "check1", "responseTimeout": 2000,
                    "interval": 2000, "healthyThreshold": 2,
                    "unhealthyThreshold": 3}
    launch_config = {"imageUuid": HEALTH_CHECK_IMAGE_UUID,
                     "healthCheck": health_check
                     }

    if protocol == "http":
        health_check["requestLine"] = "GET /name.html HTTP/1.0"
        health_check["port"] = 80

    if protocol == "tcp":
        health_check["requestLine"] = ""
        health_check["port"] = 22

    if strategy is not None:
        health_check["strategy"] = strategy
        if strategy == "recreateOnQuorum":
            health_check['recreateOnQuorumStrategyConfig'] = {"quorum": qcount}
    if port is not None:
        launch_config["ports"] = [str(port)+":22/tcp"]
    if labels is not None:
        launch_config["labels"] = labels
    service, env = create_env_and_svc_activate_launch_config(
        super_client, client, launch_config, scale)
    container_list = get_service_container_list(super_client, service)
    for con in container_list:
        wait_for_condition(
            client, con,
            lambda x: x.healthState == 'healthy',
            lambda x: 'State is: ' + x.healthState)
    return env, service


def check_for_healthstate(client, super_client, service):
    container_list = get_service_container_list(super_client, service)
    for con in container_list:
        wait_for_condition(
            client, con,
            lambda x: x.healthState == 'healthy',
            lambda x: 'State is: ' + x.healthState)


def mark_container_unhealthy(con, port):
    hostIpAddress = con.dockerHostIp

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostIpAddress, username="root",
                password="root", port=port)
    cmd = "mv /usr/share/nginx/html/name.html name1.html"

    logger.info(cmd)
    stdin, stdout, stderr = ssh.exec_command(cmd)


def mark_container_healthy(con, port):
    hostIpAddress = con.dockerHostIp

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostIpAddress, username="root",
                password="root", port=port)
    cmd = "mv name1.html /usr/share/nginx/html/name.html"

    logger.info(cmd)
    stdin, stdout, stderr = ssh.exec_command(cmd)
