#!/usr/bin/env ruby
require 'yaml'
require 'ipaddr'
require 'fileutils'

class ClusterMenu
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
    puts "\nВерсия: #{cfg['k3s_version']}; провайдер: #{cfg['vm_provider']}"
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
    data = inventory
    name = ask('Имя нового worker, например k3s-worker3')
    raise 'Имя: строчные латинские буквы, цифры, дефисы; до 63 символов' unless name.match?(/\A[a-z][a-z0-9-]{0,61}[a-z0-9]\z/)
    all = data['all']['children'].values.flat_map { |g| g['hosts'].to_a }
    raise 'Имя или vagrant_id уже заняты' if all.any? { |n, h| n == name || h['vagrant_id'] == name }
    ip_text = ask('IPv4 нового worker')
    ip = IPAddr.new(ip_text)
    raise 'Нужен одиночный IPv4' unless ip.ipv4? && ip_text == ip.to_s
    network = IPAddr.new("#{all.first.last['ansible_host']}/#{settings['private_network_prefix']}")
    raise 'IP должен быть в подсети кластера, не адресом сети или broadcast' unless network.include?(ip) && ip != network.to_range.first && ip != network.to_range.last
    raise 'IP уже занят в inventory' if all.any? { |_, h| h['ansible_host'] == ip_text }
    return unless confirm("Добавить #{name} (#{ip_text}) и применить конфигурацию?")
    hosts(data, 'workers')[name] = {'ansible_host' => ip_text, 'vagrant_id' => name}
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

  def resources
    data = inventory
    nodes = data['all']['children'].values.flat_map { |g| g['hosts'].to_a }
    nodes.each_with_index { |(name, _), i| puts "#{i + 1}. #{name}" }
    selection = ask('Номер узла (0 — отмена)')
    return if selection == '0'
    raise 'Неверный номер' unless selection.match?(/\A[1-9]\d*\z/) && selection.to_i <= nodes.length
    name, host = nodes[selection.to_i - 1]
    cpu = ask('CPU (1–32)')
    ram = ask('RAM в MB (1024–65536)')
    raise 'Неверные CPU/RAM' unless cpu.match?(/\A\d+\z/) && ram.match?(/\A\d+\z/) && (1..32).cover?(cpu.to_i) && (1024..65536).cover?(ram.to_i)
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
    return puts('Эта версия уже указана в настройках.') if value == settings['k3s_version']
    # Validate the release before touching VMs or configuration.
    run('curl', '--fail', '--silent', '--show-error', '--location', '--head', '--connect-timeout', '10', '--max-time', '30', '--output', '/dev/null', "https://github.com/k3s-io/k3s/releases/download/#{value}/sha256sum-arm64.txt")
    existing = !Dir.glob(File.join(@root, '.vagrant/machines/*/*/id')).empty?
    if existing
      puts 'Смена версии в этом меню выполняется пересозданием лаборатории, все данные VM будут удалены.'
      return unless confirm("Пересоздать кластер на #{value}? Для обновления с сохранением данных используйте отдельную процедуру из README.")
      run('./cluster.sh', 'destroy')
    else
      return unless confirm("Создать кластер на #{value}?")
    end
    set_values('k3s_version' => value, 'allow_version_change' => false)
    run('./cluster.sh', 'up', '--verify')
  end

  def start
    loop do
      show
      puts "\n1. Создать / применить конфигурацию\n2. Удалить кластер\n3. Состояние VM и узлов\n4. Проверить сеть и Traefik\n5. Добавить worker\n6. Удалить worker\n7. Изменить CPU / RAM узла\n8. Изменить версию k3s\n0. Выход"
      begin
        case ask('Выбери номер')
        when '1' then run('./cluster.sh', 'up', '--verify')
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
  root = File.expand_path('..', __dir__)
  ENV['VAGRANT_CWD'] = root
  ENV['VAGRANT_DOTFILE_PATH'] = File.join(root, '.vagrant')
  ClusterMenu.new(root).start
end
