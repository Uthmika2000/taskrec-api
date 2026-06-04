// Team Controller - Backend MVC Architecture
const Team = require('../models/Team');
const User = require('../models/User');
const Notification = require('../models/Notification');
const { getAccessibleTeamIds } = require('../utils/access');

// @desc    Create new team
// @route   POST /api/teams
// @access  Private (Admin, Scrum Master)
exports.createTeam = async (req, res, next) => {
  try {
    const { name, description, memberIds } = req.body;

    // Validate required fields
    if (!name) {
      return res.status(400).json({ success: false, message: 'Team name is required' });
    }

    const teamMemberIds = Array.from(new Set([req.user._id.toString(), ...(memberIds || []).map(id => id.toString())]));

    const team = await Team.create({
      name,
      description: description || '',
      adminId: req.user._id,
      memberIds: teamMemberIds,
    });

    await User.findByIdAndUpdate(req.user._id, { $addToSet: { teamIds: team._id } });

    // Add team to users' teamIds
    if (memberIds && memberIds.length > 0) {
      await User.updateMany(
        { _id: { $in: memberIds } },
        { $addToSet: { teamIds: team._id } }
      );
    }

    const populated = await Team.findById(team._id)
      .populate('memberIds', '-passwordHash')
      .populate('adminId', '-passwordHash');

    res.status(201).json({ success: true, data: populated });
  } catch (error) {
    next(error);
  }
};

// @desc    Get team by ID with members and sprints
// @route   GET /api/teams/:id
// @access  Private
exports.getTeam = async (req, res, next) => {
  try {
    const team = await Team.findById(req.params.id)
      .populate('memberIds', '-passwordHash')
      .populate('adminId', '-passwordHash')
      .populate({
        path: 'sprintIds',
        populate: { path: 'taskIds' },
      });

    if (!team) {
      return res.status(404).json({ success: false, message: 'Team not found' });
    }

    res.json({ success: true, data: team });
  } catch (error) {
    next(error);
  }
};

// @desc    Get all teams
// @route   GET /api/teams
// @access  Private
exports.getTeams = async (req, res, next) => {
  try {
    const accessibleTeamIds = await getAccessibleTeamIds(req.user._id);
    const teams = await Team.find({ _id: { $in: accessibleTeamIds } })
      .populate('memberIds', '-passwordHash')
      .populate('adminId', '-passwordHash')
      .sort({ createdAt: -1 });

    res.json({ success: true, data: teams });
  } catch (error) {
    next(error);
  }
};

// @desc    Invite user to team by email
// @route   POST /api/teams/:id/invite
// @access  Private (Admin, Scrum Master)
exports.inviteUser = async (req, res, next) => {
  try {
    const { email } = req.body;

    if (!email) {
      return res.status(400).json({ success: false, message: 'Email is required' });
    }

    const team = await Team.findById(req.params.id);
    if (!team) {
      return res.status(404).json({ success: false, message: 'Team not found' });
    }

    // Find user by email
    const user = await User.findOne({ email: email.toLowerCase() });
    if (!user) {
      return res.status(404).json({ success: false, message: 'User not found with this email' });
    }

    // Check if user is already a member
    const isAlreadyMember = team.memberIds.some(memberId => memberId.toString() === user._id.toString());
    if (isAlreadyMember) {
      return res.status(400).json({ success: false, message: 'User is already a team member' });
    }

    const existingInvite = await Notification.findOne({
      recipientId: user._id,
      teamId: team._id,
      type: 'team_invite',
      status: 'pending',
    });

    if (existingInvite) {
      return res.status(400).json({ success: false, message: 'Invitation already sent to this user' });
    }

    await Notification.create({
      recipientId: user._id,
      senderId: req.user._id,
      teamId: team._id,
      type: 'team_invite',
      title: `Team invitation from ${req.user.name}`,
      message: `${req.user.name} invited you to join ${team.name}.`,
      status: 'pending',
      read: false,
    });

    res.json({
      success: true,
      data: { teamId: team._id, invitedUserId: user._id },
      message: `${user.name} has been invited to ${team.name}.`,
    });
  } catch (error) {
    next(error);
  }
};

// @desc    Update team
// @route   PATCH /api/teams/:id
// @access  Private
exports.updateTeam = async (req, res, next) => {
  try {
    const { name, description } = req.body;

    const team = await Team.findById(req.params.id);
    if (!team) {
      return res.status(404).json({ success: false, message: 'Team not found' });
    }

    if (name) team.name = name;
    if (description !== undefined) team.description = description;

    await team.save();

    const populated = await Team.findById(team._id)
      .populate('memberIds', '-passwordHash')
      .populate('adminId', '-passwordHash');

    res.json({ success: true, data: populated });
  } catch (error) {
    next(error);
  }
};

// @desc    Delete team
// @route   DELETE /api/teams/:id
// @access  Private (Admin, Scrum Master)
exports.deleteTeam = async (req, res, next) => {
  try {
    const team = await Team.findById(req.params.id);
    if (!team) {
      return res.status(404).json({ success: false, message: 'Team not found' });
    }

    // Remove team from all members' teamIds
    await User.updateMany(
      { teamIds: req.params.id },
      { $pull: { teamIds: req.params.id } }
    );

    await Team.findByIdAndDelete(req.params.id);
    res.json({ success: true, message: 'Team deleted successfully' });
  } catch (error) {
    next(error);
  }
};

// @desc    Remove member from team
// @route   DELETE /api/teams/:id/members/:userId
// @access  Private (Admin, Scrum Master)
exports.removeMember = async (req, res, next) => {
  try {
    const { userId } = req.params;

    const team = await Team.findById(req.params.id);
    if (!team) {
      return res.status(404).json({ success: false, message: 'Team not found' });
    }

    // Remove user from members array
    team.memberIds = team.memberIds.filter(
      (member) => member.toString() !== userId
    );

    await team.save();

    // Remove team from user's teamIds
    await User.findByIdAndUpdate(userId, { $pull: { teamIds: req.params.id } });

    const populated = await Team.findById(team._id)
      .populate('memberIds', '-passwordHash')
      .populate('adminId', '-passwordHash');

    res.json({ success: true, data: populated });
  } catch (error) {
    next(error);
  }
};
