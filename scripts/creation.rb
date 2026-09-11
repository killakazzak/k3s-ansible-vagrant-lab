require 'ipaddr'
module Creation
  def node_prefix
    prefix = settings.fetch('menu_node_prefix', 'k8s-cluster1')
    prefix == 'k3s' ? 'k8s-cluster1' : prefix
  end

  def next_node_name(role)
    names = inventory['all']['children'].values.flat_map { |g| g['hosts'].flat_map { |n,h| [n,h['vagrant_id']] } }
    index = 1
    index += 1 while names.include?("#{node_prefix}-#{role}#{index}")
    "#{node_prefix}-#{role}#{index}"
  end

  def next_node_ip(role)
    cfg = settings
    entries = inventory['all']['children'].values.flat_map { |g| g['hosts'].values }
    raise 'Кластер пуст. Сначала создайте кластер.' if entries.empty?
    network = IPAddr.new("#{entries.first['ansible_host']}/#{cfg['private_network_prefix']}")
    used = entries.map { |h| h['ansible_host'] }
    start = role == 'server' ? 11 : 21
    size = network.to_range.last.to_i - network.to_i
    offsets = (start...size).to_a + (2...[start,size].min).to_a
    offset = offsets.find { |i| !used.include?(IPAddr.new(network.to_i+i,Socket::AF_INET).to_s) }
    raise 'В подсети нет свободных адресов в inventory' unless offset
    IPAddr.new(network.to_i+offset,Socket::AF_INET).to_s
  end

  def add_with_resources(group, params)
    cfg = settings
    raise 'Включите embedded etcd для нескольких master' if group == 'server' && !cfg['k3s_embedded_etcd']
    resources = {}
    [['cpu', 'vm_cpus', 1, 32], ['ram', 'vm_memory_mb', cfg['rancher_enabled'] ? 4096 : 1024, 65536], ['disk', 'vm_disk_gb', 25, 2048]].each do |input, key, min, max|
      default = cfg.fetch(key, {}).fetch(group, key == 'vm_disk_gb' ? 25 : min)
      value = params.fetch(input, default).to_s
      raise "#{input}: целое число #{min}–#{max}" unless value.match?(/\A[0-9]+\z/) && (min..max).cover?(value.to_i)
      resources[key] = value.to_i
    end
    raise 'Диск больше 25 ГБ поддерживается только с VirtualBox' if resources['vm_disk_gb'] > 25 && cfg['vm_provider'] != 'virtualbox'
    add_node(group, group == 'server' ? 'master' : 'worker', resources)
  end

  def creation_plan(params)
    cfg = settings
    old = inventory
    int = lambda do |key, min, max|
      value = params.fetch(key).to_s
      raise "#{key}: целое число #{min}–#{max}" unless value.match?(/\A[0-9]+\z/) && (min..max).cover?(value.to_i)
      value.to_i
    end
    masters = int.call('masters', 1, 7)
    workers = int.call('workers', 1, 32)
    raise 'Включите embedded etcd для нескольких master' if masters > 1 && !cfg['k3s_embedded_etcd']
    cpu = {}; ram = {}; disk = {}
    %w[server workers].each do |role|
      cpu[role] = int.call("#{role}_cpu", 1, 32)
      ram[role] = int.call("#{role}_ram", cfg['rancher_enabled'] ? 4096 : 1024, 65536)
      disk[role] = int.call("#{role}_disk", 25, 2048)
    end
    raise 'Диск больше 25 ГБ поддерживается только с VirtualBox' if cfg['vm_provider'] != 'virtualbox' && disk.values.any? { |v| v > 25 }
    first = hosts(old, 'server').values.first
    current = IPAddr.new(first ? "#{first['ansible_host']}/#{cfg['private_network_prefix']}" : cfg.fetch('private_network_cidr', '192.168.58.0/24'))
    mode = params.fetch('network_mode')
    raise 'Неверный режим сети' unless %w[existing new].include?(mode)
    cidr = mode == 'existing' ? "#{current}/#{cfg['private_network_prefix']}" : params.fetch('network').to_s
    raise 'Сеть должна быть в CIDR, например 192.168.59.0/24' unless cidr.match?(/\A\d+\.\d+\.\d+\.\d+\/(1[6-9]|2[0-8])\z/)
    network = IPAddr.new(cidr)
    raise 'Укажите адрес сети, а не узла' unless network.to_s == cidr.split('/')[0]
    raise 'Нужна частная IPv4-подсеть' unless network.ipv4? && ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'].any? { |n| IPAddr.new(n).include?(network.to_range.first) && IPAddr.new(n).include?(network.to_range.last) }
    %w[pod_subnet service_subnet].each do |key|
      other = IPAddr.new(cfg.fetch(key))
      raise "Сеть пересекается с #{key}" if network.include?(other.to_range.first) || other.include?(network.to_range.first)
    end
    prefix = cidr.split('/')[1].to_i
    raise 'Недостаточно адресов в подсети' if masters + workers + 3 > 2**(32-prefix)
    # Reserve .1 for the host adapter. Prefer the familiar .11/.21 layout.
    offset = (21 + workers < 2**(32-prefix)-1) ? [11,21] : [2,2+masters]
    existing = !Dir.glob(File.join(@root,'.vagrant/machines/*/*/id')).empty?
    if existing
      unchanged = mode == 'existing' && masters == hosts(old,'server').size && workers == hosts(old,'workers').size
      old['all']['children'].each do |role,g|
        unchanged &&= g['hosts'].values.all? { |h| h.fetch('vm_cpus',cfg['vm_cpus'][role]) == cpu[role] && h.fetch('vm_memory_mb',cfg['vm_memory_mb'][role]) == ram[role] && h.fetch('vm_disk_gb',cfg.fetch('vm_disk_gb',{}).fetch(role,25)) == disk[role] }
      end
      raise 'В выбранном кластере уже есть VM. Для второго кластера нажмите «Новый кластер» и задайте отдельную подсеть. CPU/ОЗУ текущих узлов меняйте через «Настроить», состав — через добавление и удаление узлов. Для смены сети или диска требуется пересоздание выбранного кластера.' unless unchanged
      return [old, {}]
    end
    name_prefix = node_prefix
    raise 'Некорректный префикс имён' unless name_prefix.match?(/\A[a-z][a-z0-9-]{0,40}\z/)
    generated = {'all'=>{'children'=>{}}}
    [['server','master',masters,offset[0]],['workers','worker',workers,offset[1]]].each do |role,label,total,start|
      generated['all']['children'][role] = {'hosts'=>{}}
      total.times do |i|
        name = "#{name_prefix}-#{label}#{i+1}"
        generated['all']['children'][role]['hosts'][name] = {'ansible_host'=>IPAddr.new(network.to_i+start+i,Socket::AF_INET).to_s,'vagrant_id'=>name,'vm_cpus'=>cpu[role],'vm_memory_mb'=>ram[role],'vm_disk_gb'=>disk[role]}
      end
    end
    [generated, {'vm_cpus'=>cpu,'vm_memory_mb'=>ram,'vm_disk_gb'=>disk,'private_network_prefix'=>prefix}]
  end

  def create_with_resources(params)
    data, changes = creation_plan(params)
    if !changes.empty?
      set_values(changes)
      write(@inventory, YAML.dump(data))
    end
    run('./cluster.sh','up','--verify')
  end
end
