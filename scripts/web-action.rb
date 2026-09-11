#!/usr/bin/env ruby
require_relative 'menu'
$stdout.sync = true
$stderr.sync = true
class WebAction < ClusterMenu
  def initialize(root, answers)
    super(root)
    @answers = answers
  end
  def ask(prompt)
    raise 'Недостаточно параметров операции' if @answers.empty?
    @answers.shift.to_s
  end
  def confirm(message)
    puts message
    true # HTTP server validates explicit confirmation before starting this adapter.
  end
end
if $PROGRAM_NAME == __FILE__
  begin
    root = File.expand_path('..', __dir__)
    ENV['VAGRANT_CWD'] = root
    ENV['VAGRANT_DOTFILE_PATH'] = File.join(root, '.vagrant')
    request = JSON.parse(STDIN.read)
    raise 'Нет подтверждения' unless request['confirmed'] == true
    action = request.fetch('action')
    params = request.fetch('params', {})
    base = ClusterMenu.new(root)
    data = base.inventory
    groups = data['all']['children']
    node = params['node']
    answers = case action
    when 'create' then [params.fetch('masters'), params.fetch('workers')]
    when 'add_master', 'add_worker' then [params.fetch('name'), params.fetch('ip')]
    when 'remove_master', 'remove_worker'
      group = action == 'remove_master' ? 'server' : 'workers'
      index = groups.fetch(group).fetch('hosts').keys.index(node)
      raise 'Узел не найден' unless index
      [index + 1]
    when 'resources'
      index = groups.values.flat_map { |g| g['hosts'].keys }.index(node)
      raise 'Узел не найден' unless index
      [index + 1, params.fetch('cpu'), params.fetch('ram')]
    when 'version' then [params.fetch('version')]
    when 'destroy', 'verify' then []
    else raise 'Неизвестная операция'
    end
    menu = WebAction.new(root, answers)
    if ['destroy', 'verify'].include?(action)
      menu.run('./cluster.sh', action)
    else
      method = {'create' => :create_cluster, 'add_master' => :add_master, 'add_worker' => :add_worker,
                'remove_master' => :remove_master, 'remove_worker' => :remove_worker,
                'resources' => :resources, 'version' => :version}.fetch(action)
      menu.public_send(method)
    end
  rescue StandardError => e
    warn "Ошибка: #{e.message}"
    exit 1
  end
end
