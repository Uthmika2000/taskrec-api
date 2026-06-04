const Notification = require('../models/Notification');
const Team = require('../models/Team');
const User = require('../models/User');

function toNotificationResponse(notification) {
  return notification;
}

async function loadNotificationForUser(notificationId, userId) {
  return Notification.findOne({ _id: notificationId, recipientId: userId })
    .populate('senderId', 'name email role')
    .populate('teamId', 'name');
}

exports.listNotifications = async (req, res, next) => {
  try {
    const notifications = await Notification.find({ recipientId: req.user._id })
      .sort({ createdAt: -1 })
      .populate('senderId', 'name email role')
      .populate('teamId', 'name');

    res.json({ success: true, data: notifications.map(toNotificationResponse) });
  } catch (error) {
    next(error);
  }
};

exports.markAsRead = async (req, res, next) => {
  try {
    const notification = await loadNotificationForUser(req.params.id, req.user._id);

    if (!notification) {
      return res.status(404).json({ success: false, message: 'Notification not found' });
    }

    notification.read = true;
    if (notification.status === 'pending') {
      notification.status = 'read';
    }
    await notification.save();

    res.json({ success: true, data: notification });
  } catch (error) {
    next(error);
  }
};

exports.markAllAsRead = async (req, res, next) => {
  try {
    await Notification.updateMany(
      { recipientId: req.user._id },
      { $set: { read: true }, $currentDate: { actionedAt: true } }
    );

    res.json({ success: true, message: 'All notifications marked as read' });
  } catch (error) {
    next(error);
  }
};

async function respondToTeamInvite(req, res, next, nextStatus) {
  try {
    const notification = await loadNotificationForUser(req.params.id, req.user._id);

    if (!notification) {
      return res.status(404).json({ success: false, message: 'Notification not found' });
    }

    if (notification.type !== 'team_invite') {
      return res.status(400).json({ success: false, message: 'This notification cannot be actioned' });
    }

    if (notification.status !== 'pending') {
      return res.status(400).json({ success: false, message: 'This invitation has already been handled' });
    }

    const team = await Team.findById(notification.teamId);
    if (!team) {
      return res.status(404).json({ success: false, message: 'Team not found' });
    }

    if (nextStatus === 'accepted') {
      const isAlreadyMember = team.memberIds.some(memberId => memberId.toString() === req.user._id.toString());

      if (!isAlreadyMember) {
        team.memberIds.push(req.user._id);
        await team.save();
      }

      await User.findByIdAndUpdate(req.user._id, { $addToSet: { teamIds: team._id } });
    }

    notification.status = nextStatus;
    notification.read = true;
    notification.actionedAt = new Date();
    await notification.save();

    const populatedTeam = await Team.findById(team._id)
      .populate('memberIds', '-passwordHash')
      .populate('adminId', '-passwordHash');

    res.json({
      success: true,
      data: {
        notification,
        team: populatedTeam,
      },
      message: nextStatus === 'accepted' ? 'Invitation accepted' : 'Invitation rejected',
    });
  } catch (error) {
    next(error);
  }
}

exports.acceptNotification = async (req, res, next) => {
  return respondToTeamInvite(req, res, next, 'accepted');
};

exports.rejectNotification = async (req, res, next) => {
  return respondToTeamInvite(req, res, next, 'rejected');
};