require 'stringio'
require_relative '../scripts/menu'
class MenuNavigationTest < ClusterMenu
  attr_reader :commands
  def initialize
    @root = Dir.pwd
    @commands = []
  end
  def show; end
  def show_web_link; end
  def print_menu; end
  def cluster_profiles; [['default', @root]]; end
  def run(*args); @commands << args; end
  def create_cluster; raise 'Opening the console must not create a cluster'; end
end
input, output = $stdin, $stdout
begin
  $stdin = StringIO.new("1\n0\n")
  $stdout = StringIO.new
  menu = MenuNavigationTest.new
  menu.start
  raise 'Wrong first action' unless menu.commands == [[File.join(Dir.pwd, 'cluster.sh'), 'web-start']]
ensure
  $stdin, $stdout = input, output
end
puts 'First menu action opens the console without creating a cluster; exit works.'
