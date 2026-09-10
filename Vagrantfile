require "yaml"
require "ipaddr"
root = File.dirname(__FILE__)
settings = YAML.load_file(File.join(root, "ansible/group_vars/all.yml"))
groups = YAML.load_file(File.join(root, "ansible/inventory.yml")).fetch("all").fetch("children")
raise "Exactly one server is supported" unless groups.fetch("server").fetch("hosts").size == 1
raise "At least one worker is required" if groups.fetch("workers").fetch("hosts").empty?
nodes = groups.flat_map { |role, group| group.fetch("hosts").map { |name, host| [role, name, host] } }
%w[vagrant_id ansible_host].each do |key|
  values = nodes.map { |_, _, host| host.fetch(key) }
  raise "Duplicate #{key}" unless values.uniq == values
end
names = nodes.map { |_, name, _| name }
raise "Duplicate hostname" unless names.uniq == names
network = IPAddr.new("#{nodes.first.last.fetch('ansible_host')}/#{settings.fetch('private_network_prefix')}")
raise "All nodes must share a subnet" unless nodes.all? { |_, _, host| network.include?(IPAddr.new(host.fetch('ansible_host'))) }
Vagrant.configure("2") do |config|
  config.vm.box = settings.fetch("vm_box")
  config.vm.box_version = settings.fetch("vm_box_version")
  config.vm.box_architecture = settings.fetch("vm_architecture")
  config.vm.synced_folder ".", "/vagrant", disabled: true
  config.vm.boot_timeout = settings.fetch("vm_boot_timeout")
  config.ssh.username = settings.fetch("ansible_user")
  nodes.each do |role, hostname, host|
    config.vm.define host.fetch("vagrant_id") do |node|
      node.vm.hostname = hostname
      node.vm.network "private_network", ip: host.fetch("ansible_host"),
        netmask: IPAddr.new("255.255.255.255").mask(settings.fetch("private_network_prefix")).to_s
      node.vm.provider settings.fetch("vm_provider") do |provider|
        provider.name = "#{settings.fetch('vm_name_prefix')}#{host.fetch('vagrant_id')}"
        provider.cpus = host.fetch("vm_cpus", settings.fetch("vm_cpus").fetch(role))
        provider.memory = host.fetch("vm_memory_mb", settings.fetch("vm_memory_mb").fetch(role))
      end
    end
  end
end
