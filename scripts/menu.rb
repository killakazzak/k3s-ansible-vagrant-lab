#!/usr/bin/env ruby
require 'yaml'
require 'ipaddr'
require 'fileutils'
require 'json'
require 'open3'
require 'shellwords'
require 'uri'
require_relative 'creation'

class ClusterMenu
  include Creation
  def initialize(root)
    @root = root
    @settings = File.join(root, 'ansible/group_vars/all.yml')
    @inventory = File.join(root, 'ansible/inventory.yml')
  end

  def ask(prompt)
    print "#{prompt}: "
    line = $stdin.gets
    raise EOFError unless line
    line.strip
  end

  def confirm(message)
    puts message
    ask('1 — подтвердить, 0 — отмена') == '1'
  end

  def run(*args)
    raise "Команда завершилась с ошибкой: #{args.first}" unless system(*args, chdir: @root)
  end

  def capture(*args)
    output, error, status = Open3.capture3(*args, chdir: @root)
    raise "Команда завершилась с ошибкой: #{args.first}: #{error.strip}" unless status.success?
    output
  end

  def count(prompt, default, maximum)
    value = ask("#{prompt} [#{default}], Enter — оставить")
    return default if value.empty?
    raise "Нужно целое число от 1 до #{maximum}" unless value.match?(/\A[1-9]\d*\z/) && value.to_i <= maximum
    value.to_i
  end

  def create_cluster
    data = inventory
    if hosts(data, 'server').empty?
      cfg = settings
      params = {'rancher_enabled'=>count('Компоненты: 1 — Kubernetes + Traefik, 2 — также Rancher',1,2)==2,'masters'=>count('Сколько master',1,7),'workers'=>count('Сколько workers',2,32),'network_mode'=>'existing'}
      %w[server workers].each do |role|
        params[role+'_cpu'] = cfg['vm_cpus'][role]
        params[role+'_ram'] = cfg['vm_memory_mb'][role]
        params[role+'_disk'] = cfg.fetch('vm_disk_gb',{}).fetch(role,25)
      end
      return unless confirm('Создать новый кластер с указанным числом узлов и ресурсами по умолчанию?')
      return create_with_resources(params)
    end
    component_rancher = Dir.glob(File.join(@root,'.vagrant/machines/*/*/id')).empty? ? count('Компоненты: 1 — Kubernetes + Traefik, 2 — также Rancher',1,2)==2 : settings['rancher_enabled']
    masters = count('Сколько master', hosts(data, 'server').length, 7)
    workers = count('Сколько workers', hosts(data, 'workers').length, 32)
    raise 'Для нескольких master включите k3s_embedded_etcd' if masters > 1 && !settings['k3s_embedded_etcd']
    changed = masters != hosts(data, 'server').length || workers != hosts(data, 'workers').length
    if changed && !Dir.glob(File.join(@root, '.vagrant/machines/*/*/id')).empty?
      raise 'VM уже существуют. Меняйте состав пунктами 5/6/9/10 либо сначала удалите кластер пунктом 2. Текущие VM и inventory не изменены.'
    end
    if changed
      cfg = settings
      first_ip = hosts(data, 'server').values.first.fetch('ansible_host')
      network = IPAddr.new("#{first_ip}/#{cfg['private_network_prefix']}")
      prefix = cfg.fetch('menu_node_prefix', 'k3s')
      raise 'Некорректный menu_node_prefix' unless prefix.match?(/\A[a-z][a-z0-9-]{0,40}\z/)
      generated = {'all' => {'children' => {}}}
      [['server', 'master', masters, cfg.fetch('menu_master_ip_start', 11)],
       ['workers', 'worker', workers, cfg.fetch('menu_worker_ip_start', 21)]].each do |group, role, size, offset|
        entries = {}
        size.times do |i|
          address = IPAddr.new(network.to_i + Integer(offset) + i, Socket::AF_INET)
          raise 'Адрес узла вне подсети или совпадает с network/broadcast' unless network.include?(address) && address != network.to_range.first && address != network.to_range.last
          name = "#{prefix}-#{role}#{i + 1}"
          entries[name] = {'ansible_host' => address.to_s, 'vagrant_id' => name}
        end
        generated['all']['children'][group] = {'hosts' => entries}
      end
      ips = generated['all']['children'].values.flat_map { |g| g['hosts'].values.map { |h| h['ansible_host'] } }
      raise 'Диапазоны адресов master и worker пересекаются' unless ips.uniq == ips
      data = generated
    end
    puts 'Чётное число master не увеличивает устойчивость etcd относительно предыдущего нечётного; обычно выбирают 1, 3 или 5.' if masters.even?
    cfg = settings
    total_ram = data['all']['children'].sum { |role, g| g['hosts'].values.sum { |h| h.fetch('vm_memory_mb', cfg['vm_memory_mb'][role]) } }
    puts "Итого: #{masters} master, #{workers} workers, #{total_ram} MB RAM для VM."
    data['all']['children'].each_value { |g| g['hosts'].each { |name, h| puts "  #{name}: #{h['ansible_host']}" } }
    return unless confirm('Создать / применить этот состав кластера?')
    set_values('rancher_enabled'=>component_rancher)
    write(@inventory, YAML.dump(data)) if changed
    run('./cluster.sh', 'up', '--verify')
  end

  def settings
    YAML.load_file(@settings)
  end

  def inventory
    YAML.load_file(@inventory)
  end

  def hosts(data, group)
    data.fetch('all').fetch('children').fetch(group).fetch('hosts')
  end

  def write(path, content)
    FileUtils.mkdir_p(File.join(@root, '.cache/menu-backups'), mode: 0700)
    backup = File.join(@root, '.cache/menu-backups', "#{File.basename(path)}-#{Time.now.strftime('%Y%m%d%H%M%S%N')}")
    FileUtils.cp(path, backup)
    temp = path + '.menu-tmp'
    File.write(temp, content)
    File.rename(temp, path)
  end

  def set_values(values)
    text = File.read(@settings)
    values.each do |key, value|
      raise "Параметр #{key} не найден" unless text.match?(/^#{Regexp.escape(key)}:/)
      # Flow YAML generated from trusted scalar/map input; preserve other comments and Jinja.
      require 'json'
      text = text.sub(/^#{Regexp.escape(key)}:.*$/, "#{key}: #{JSON.generate(value)}")
    end
    write(@settings, text)
  end

  def show
    cfg = settings
    if inventory['all']['children'].values.all? { |g| g['hosts'].empty? }
      puts "\nКластер пуст. Inventory не содержит узлов. Для создания выберите пункт 4."
      return
    end
    begin
      output = capture('vagrant', 'status', '--machine-readable')
      states = output.lines.map { |line| line.strip.split(',') }.select { |parts| parts[2] == 'state' }.map { |parts| [parts[1], parts[3]] }.to_h
      puts(states.values.all? { |v| v == 'not_created' } && !states.empty? ? "\nКластер не создан / ВМ удалены. Ниже сохранённая конфигурация для развёртывания." : "\nСостояние ВМ: #{states.map { |k,v| k + ': ' + v }.join(', ')}")
    rescue StandardError
      puts "\nСостояние ВМ проверить не удалось. Ниже только сохранённая конфигурация."
    end
    puts "\nВерсия: #{cfg['k3s_version']}; провайдер: #{cfg['vm_provider']}"
    puts "Текущий inventory (ansible/inventory.yml) — сохранённая конфигурация узлов; их наличие и запуск этим списком не подтверждаются."
    inventory['all']['children'].each do |group, entry|
      entry['hosts'].each do |name, host|
        cpu = host.fetch('vm_cpus', cfg['vm_cpus'][group])
        ram = host.fetch('vm_memory_mb', cfg['vm_memory_mb'][group])
        puts "  #{name}: #{host['ansible_host']}, #{cpu} CPU, #{ram} MB RAM"
      end
    end
  end

  def select_worker(data)
    names = hosts(data, 'workers').keys
    names.each_with_index { |name, i| puts "#{i + 1}. #{name}" }
    value = ask('Номер worker (0 — отмена)')
    return nil if value == '0'
    raise 'Неверный номер' unless value.match?(/\A[1-9]\d*\z/) && value.to_i <= names.length
    names[value.to_i - 1]
  end

  def add_worker
    add_node('workers', 'worker')
  end

  def add_master
    puts 'Для отказоустойчивости etcd нужны минимум 3 master. Два master требуют доступности обоих.'
    raise 'Включите k3s_embedded_etcd в настройках' unless settings['k3s_embedded_etcd']
    add_node('server', 'master')
  end

  def add_node(group, role, resources = {})
    data = inventory
    raise 'Кластер пуст. Сначала создайте кластер.' if hosts(data, 'server').empty?
    suggested = next_node_name(role)
    name = ask("Имя нового #{role} [#{suggested}]").strip
    name = suggested if name.empty?
    raise 'Имя: строчные латинские буквы, цифры, дефисы; до 63 символов' unless name.match?(/\A[a-z][a-z0-9-]{0,61}[a-z0-9]\z/)
    all = data['all']['children'].values.flat_map { |g| g['hosts'].to_a }
    raise 'Имя или vagrant_id уже заняты' if all.any? { |n, h| n == name || h['vagrant_id'] == name }
    ip_text = ask("IPv4 нового #{role}")
    ip = IPAddr.new(ip_text)
    raise 'Нужен одиночный IPv4' unless ip.ipv4? && ip_text == ip.to_s
    network = IPAddr.new("#{all.first.last['ansible_host']}/#{settings['private_network_prefix']}")
    raise 'IP должен быть в подсети кластера, не адресом сети или broadcast' unless network.include?(ip) && ip != network.to_range.first && ip != network.to_range.last
    raise 'IP уже занят в inventory' if all.any? { |_, h| h['ansible_host'] == ip_text }
    return unless confirm("Добавить #{name} (#{ip_text}) и применить конфигурацию?")
    hosts(data, group)[name] = {'ansible_host' => ip_text, 'vagrant_id' => name}.merge(resources)
    write(@inventory, YAML.dump(data))
    run('./cluster.sh', 'up', '--verify')
  end

  def remove_worker
    data = inventory
    raise 'Должен остаться хотя бы один worker' if hosts(data, 'workers').length <= 1
    name = select_worker(data)
    return unless name
    return unless confirm("Удалить #{name}? Выполнится drain, затем удаление VM. Данные её диска и emptyDir будут потеряны; локальные PV автоматически не переносятся.")
    run('./kubectl.sh', 'drain', name, '--ignore-daemonsets', '--delete-emptydir-data', '--timeout=180s')
    run('vagrant', 'destroy', '-f', hosts(data, 'workers')[name]['vagrant_id'])
    run('./kubectl.sh', 'delete', 'node', name, '--ignore-not-found=true')
    hosts(data, 'workers').delete(name)
    write(@inventory, YAML.dump(data))
    puts 'Worker удалён.'
  end

  def remove_master
    data = inventory
    masters = hosts(data, 'server')
    raise 'Последний master нельзя удалить отдельно. Для удаления всего кластера используйте пункт 2.' if masters.length <= 1
    primary = masters.keys.first
    names = masters.keys
    names.each_with_index { |name, i| puts "#{i + 1}. #{name}#{name == primary ? ' (первый master, защищён)' : ''}" }
    value = ask('Номер master (0 — отмена)')
    return if value == '0'
    raise 'Неверный номер' unless value.match?(/\A[1-9]\d*\z/) && value.to_i <= names.length
    name = names[value.to_i - 1]
    raise 'Первый master хранит адрес API и Rancher. Его отдельное удаление не поддерживается; используйте пересоздание кластера.' if name == primary
    raise 'Удаление master требует embedded etcd' unless settings['k3s_embedded_etcd']
    live = JSON.parse(capture('./kubectl.sh', 'get', 'nodes', '-o', 'json', '--request-timeout=15s')).fetch('items')
    target = live.find { |n| n['metadata']['name'] == name }
    if !target
      id = File.join(@root, '.vagrant/machines', masters[name]['vagrant_id'], settings['vm_provider'], 'id')
      raise 'Узел отсутствует в Kubernetes, но VM ещё существует. Требуется проверка состава etcd вручную.' if File.exist?(id)
      return unless confirm("VM и Node #{name} уже отсутствуют. Удалить оставшуюся запись inventory?")
      masters.delete(name)
      write(@inventory, YAML.dump(data))
      return
    end
    annotations = target['metadata'].fetch('annotations', {})
    removed = annotations['etcd.k3s.cattle.io/removed-node-name']
    member_name = annotations['etcd.k3s.cattle.io/node-name']
    already_removed = removed && !removed.empty? && !member_name
    unless already_removed
      actual = live.select { |n| n['metadata'].fetch('labels', {}).key?('node-role.kubernetes.io/etcd') }
      raise 'Состав etcd-узлов Kubernetes не совпадает с inventory; сначала устраните расхождение.' unless actual.map { |n| n['metadata']['name'] }.sort == names.sort
      raise 'Все master должны быть Ready перед изменением etcd.' unless actual.all? { |n| n.fetch('status', {}).fetch('conditions', []).any? { |c| c['type'] == 'Ready' && c['status'] == 'True' } }
      raise 'У master отсутствует имя etcd-member' unless member_name && member_name.match?(/\A[a-zA-Z0-9_.-]+\z/)
    end
    puts "После удаления останется #{masters.length - 1} master. При 1 или 2 master отказ одного узла останавливает control plane." if masters.length <= 3
    return unless confirm("Удалить #{name}? Сначала snapshot и drain, затем исключение из etcd. VM и её локальные данные будут удалены только после подтверждения k3s.")
    unless already_removed
      run('./kubectl.sh', 'get', '--raw=/readyz', '--request-timeout=15s')
      run('vagrant', 'ssh', masters[primary]['vagrant_id'], '-c', 'sudo k3s etcd-snapshot save')
      run('./kubectl.sh', 'drain', name, '--ignore-daemonsets', '--delete-emptydir-data', '--timeout=180s')
      run('./kubectl.sh', 'annotate', 'node', name, 'etcd.k3s.cattle.io/remove=true', '--overwrite')
      run('./kubectl.sh', 'wait', "node/#{name}", "--for=jsonpath={.metadata.annotations.etcd\\.k3s\\.cattle\\.io/removed-node-name}=#{member_name}", '--timeout=180s')
    end
    run('vagrant', 'destroy', '-f', masters[name]['vagrant_id'])
    run('./kubectl.sh', 'delete', 'node', name, '--ignore-not-found=true')
    masters.delete(name)
    write(@inventory, YAML.dump(data))
    run('./kubectl.sh', 'wait', '--for=condition=Ready', *masters.keys.map { |n| "node/#{n}" }, '--timeout=180s')
    puts 'Master исключён из etcd и удалён.'
  end

  def resources
    data = inventory
    nodes = data['all']['children'].values.flat_map { |g| g['hosts'].to_a }
    nodes.each_with_index { |(name, _), i| puts "#{i + 1}. #{name}" }
    selection = ask('Номер узла (0 — отмена)')
    return if selection == '0'
    raise 'Неверный номер' unless selection.match?(/\A[1-9]\d*\z/) && selection.to_i <= nodes.length
    name, host = nodes[selection.to_i - 1]
    cpu = ask('CPU (1–32)')
    minimum_ram = settings['rancher_enabled'] ? 4096 : 1024
    ram = ask("RAM в MB (#{minimum_ram}–65536)")
    raise 'Неверные CPU/RAM' unless cpu.match?(/\A\d+\z/) && ram.match?(/\A\d+\z/) && (1..32).cover?(cpu.to_i) && (minimum_ram..65536).cover?(ram.to_i)
    return unless confirm("Сохранить #{name}: #{cpu} CPU, #{ram} MB? Если VM существует, она будет перезагружена; master временно остановит API.")
    host['vm_cpus'] = cpu.to_i
    host['vm_memory_mb'] = ram.to_i
    write(@inventory, YAML.dump(data))
    id = File.join(@root, '.vagrant/machines', host['vagrant_id'], settings['vm_provider'], 'id')
    run('vagrant', 'reload', host['vagrant_id'], '--no-provision') if File.exist?(id)
    run('./cluster.sh', 'up', '--verify')
  end

  def version
    value = ask('Точная версия k3s, например v1.36.4+k3s1 (0 — отмена)')
    return if value == '0'
    raise 'Формат: vX.Y.Z+k3sN' unless value.match?(/\Av\d+\.\d+\.\d+\+k3s\d+\z/)
    if settings['rancher_enabled'] && !value.match?(/\Av1\.(34|35|36)\./)
      raise 'Rancher 2.15.1 поддерживает k3s 1.34–1.36. Выберите совместимую версию или отключите rancher_enabled до пересоздания.'
    end
    return puts('Эта версия уже указана в настройках.') if value == settings['k3s_version']
    # Validate the release before touching VMs or configuration.
    run('curl', '--fail', '--silent', '--show-error', '--location', '--head', '--connect-timeout', '10', '--max-time', '30', '--output', '/dev/null', "https://github.com/k3s-io/k3s/releases/download/#{value}/sha256sum-#{settings['vm_architecture'] == 'arm64' ? 'arm64' : 'amd64'}.txt")
    saved_inventory = inventory
    existing = !Dir.glob(File.join(@root, '.vagrant/machines/*/*/id')).empty?
    if existing
      puts 'Смена версии в этом меню выполняется пересозданием лаборатории, все данные VM будут удалены.'
      return unless confirm("Пересоздать кластер на #{value}? Для обновления с сохранением данных используйте отдельную процедуру из README.")
      run('./cluster.sh', 'destroy')
    else
      return unless confirm("Создать кластер на #{value}?")
    end
    write(@inventory, YAML.dump(saved_inventory)) if existing
    set_values('k3s_version' => value, 'allow_version_change' => false)
    if hosts(inventory, 'server').empty?
      create_cluster
    else
      run('./cluster.sh', 'up', '--verify')
    end
  end

  def cluster_profiles
    root = File.expand_path(@root)
    base = File.basename(File.dirname(root)) == '.clusters' ? File.expand_path('../..', root) : root
    profiles = [['k8s-cluster1 (default)', base]]
    Dir.glob(File.join(base, '.clusters', '*')).sort.each do |path|
      next unless File.directory?(path) && !File.symlink?(path)
      next unless File.basename(path).match?(/\A[a-z][a-z0-9-]{0,30}\z/)
      next unless File.file?(File.join(path, 'ansible/inventory.yml'))
      profiles << [File.basename(path), path]
    end
    profiles
  end

  def list_clusters
    profiles = cluster_profiles.select do |_, path|
      begin
        data = YAML.load_file(File.join(path, 'ansible/inventory.yml'))
        data.fetch('all').fetch('children').values.any? { |group| !group.fetch('hosts', {}).empty? }
      rescue StandardError
        true # Keep unreadable profiles available for diagnosis.
      end
    end
    if profiles.empty?
      puts 'Нет кластеров. Для создания выберите пункт 4.'
      return profiles
    end
    puts "\nКластеры — сохранённые профили (наличие kubeconfig не означает доступность API):"
    profiles.each_with_index do |(name, path), index|
      ready = File.file?(File.join(path, 'kubeconfig')) && File.size(File.join(path, 'kubeconfig')) > 0
      selected = File.expand_path(@root) == path ? ' ← текущий' : ''
      puts "#{index + 1}. #{name} — #{ready ? 'kubeconfig готов' : 'kubeconfig пока нет'}#{selected}"
      puts "   #{path}"
    end
    profiles
  end

  def connect_kubectl
    profiles = list_clusters
    return if profiles.empty?
    value = ask('Номер кластера для kubectl (0 — отмена)')
    return if value == '0'
    raise 'Неверный номер кластера' unless value.match?(/\A[1-9]\d*\z/) && value.to_i <= profiles.length
    name, path = profiles[value.to_i - 1]
    config = File.join(path, 'kubeconfig')
    unless File.file?(config) && File.size(config) > 0
      puts 'Доступ к кластеру пока не готов. Создайте кластер или дождитесь завершения развёртывания.'
      return
    end
    puts "\nПодключение к #{name}:"
    puts "kubectl --kubeconfig=#{Shellwords.escape(config)} get nodes -o wide"
    puts "\nЧтобы следующие команды kubectl использовали этот кластер, выполните в своём терминале:"
    puts "export KUBECONFIG=#{Shellwords.escape(config)}"
    puts "\nПроверяю подключение…"
    run(File.join(path, 'kubectl.sh'), 'get', 'nodes', '-o', 'wide', '--request-timeout=10s')
  end

  def show_web_link
    base = cluster_profiles.first.last
    path = File.join(base, '.cache/web.lock')
    if File.file?(path)
      File.open(path, 'r') do |lock|
        # A held lock belongs to the running console; an unlocked file is stale.
        unless lock.flock(File::LOCK_EX | File::LOCK_NB)
          url = JSON.parse(lock.read).fetch('url')
          uri = URI.parse(url)
          if uri.scheme == 'http' && uri.host == '127.0.0.1' && !uri.userinfo && url !~ /[\x00-\x20\x7f]/
            puts "\nВеб-интерфейс управления: #{url}\n\n"
            return
          end
        end
      end
    end
    puts "\nВеб-консоль не запущена. Запуск — пункт 12 меню или команда:"
    puts "#{Shellwords.escape(File.join(base, 'cluster.sh'))} web-start"
    puts 'После запуска откройте полный адрес, который появится в терминале.'
  rescue JSON::ParserError, KeyError, URI::InvalidURIError, SystemCallError
    puts "Веб-консоль: запустите #{Shellwords.escape(File.join(base, 'cluster.sh'))} web, чтобы получить актуальную ссылку."
  end

  MENU_GROUPS = [
    ['БЫСТРЫЙ ДОСТУП', [
      ['Открыть веб-консоль', '12'],
      ['Список кластеров', '13'],
      ['Подключение через kubectl', '14']]],
    ['КЛАСТЕР', [
      ['Создать / применить конфигурацию', '1'],
      ['Состояние VM и узлов', '3'],
      ['Проверить сеть и Traefik', '4'],
      ['Удалить кластер', '2']]],
    ['УЗЛЫ И РЕСУРСЫ', [
      ['Добавить master', '9'],
      ['Удалить master', '10'],
      ['Добавить worker', '5'],
      ['Удалить worker', '6'],
      ['Изменить CPU / RAM узла', '7'],
      ['Изменить версию k3s', '8']]],
    ['СТЕНД И КОМПОНЕНТЫ', [
      ['Остановить VM · сохранить данные', '16'],
      ['Возобновить VM стенда', '17'],
      ['Ссылки на Rancher и Traefik', '11'],
      ['Установить Rancher', '18'],
      ['Остановить веб-сервер', '15']]],
    ['ОКРУЖЕНИЕ ПЛАТФОРМЫ', [
      ['Проверить окружение', 'doctor'],
      ['Установить недостающие компоненты', 'setup']]]
  ].freeze

  def menu_action(number)
    return '0' if number == '0'
    return nil unless number.match?(/\A[1-9]\d*\z/)
    MENU_GROUPS.flat_map(&:last)[number.to_i - 1]&.last
  end

  def print_menu
    width = 48
    puts "\n  K3s Lab · Управление стендом"
    puts "  ┌────┬#{'─' * width}┐"
    index = 0
    MENU_GROUPS.each_with_index do |(title, entries), group|
      puts "  ├────┼#{'─' * width}┤" if group > 0
      puts "  │    │ #{title.ljust(width - 2)} │"
      entries.each do |label, _|
        index += 1
        puts "  │ #{index.to_s.rjust(2)} │ #{label.ljust(width - 2)} │"
      end
    end
    puts "  ├────┼#{'─' * width}┤"
    puts "  │  0 │ #{'Выход из меню'.ljust(width - 2)} │"
    puts "  └────┴#{'─' * width}┘"
    puts "  1 — открыть браузер и показать ссылку.\n\n"
  end

  def start
    show_web_link unless ENV.delete('K3S_LAB_WEB_LINK_SHOWN') == '1'
    loop do
      show
      print_menu
      begin
        case menu_action(ask('  Номер действия'))
        when '1' then create_cluster
        when '2'
          run('./cluster.sh', 'destroy') if confirm('Удалить все VM этого кластера вместе с данными?')
        when '3'
          run('./cluster.sh', 'status')
          run('./kubectl.sh', 'get', 'nodes', '-o', 'wide', '--request-timeout=10s') if File.exist?(File.join(@root, 'kubeconfig'))
        when '4' then run('./cluster.sh', 'verify')
        when '5' then add_worker
        when '6' then remove_worker
        when '7' then resources
        when '8' then version
        when '9' then add_master
        when '10' then remove_master
        when '11' then run('ansible-playbook', 'ansible/access.yml')
        when '12' then run(File.join(cluster_profiles.first.last, 'cluster.sh'), 'web-start')
        when '13' then list_clusters
        when '14' then connect_kubectl
        when '15' then run(File.join(cluster_profiles.first.last, 'cluster.sh'), 'web-stop')
        when '16' then run('./cluster.sh', 'stand-stop') if confirm('Штатно выключить VM этого стенда? Диски и данные сохранятся.')
        when '17' then run('./cluster.sh', 'stand-start')
        when '18' then run('./cluster.sh', 'rancher-install')
        when 'doctor' then system('ruby', File.join(cluster_profiles.first.last, 'scripts/environment.rb'))
        when 'setup' then run('bash', File.join(cluster_profiles.first.last, 'scripts/environment-setup.sh'))
        when '0' then break
        else puts 'Выбери номер из меню.'
        end
      rescue EOFError, Interrupt
        puts "\nВыход."
        break
      rescue StandardError => e
        warn "Ошибка: #{e.message}"
        warn 'Операция остановлена. Проверьте состояние и настройки; после устранения причины можно повторить применение.'
      end
    end
  end
end

if $PROGRAM_NAME == __FILE__
  root = File.expand_path(ENV.fetch('VAGRANT_CWD', File.expand_path('..', __dir__)))
  ENV['VAGRANT_CWD'] = root
  ENV['VAGRANT_DOTFILE_PATH'] = File.join(root, '.vagrant')
  ClusterMenu.new(root).start
end
